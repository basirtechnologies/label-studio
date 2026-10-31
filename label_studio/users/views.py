"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license."""

import logging
from urllib.parse import quote

from core.feature_flags import flag_set
from core.utils.common import load_func
from django.conf import settings
from django.contrib import auth
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from organizations.forms import OrganizationSignupForm
from organizations.models import Organization
from rest_framework.authtoken.models import Token
from users import forms
from users.forms import normalize_user_email
from users.functions import login, proceed_registration
from users.models import User

logger = logging.getLogger()


@login_required
def logout(request):
    auth.logout(request)

    if settings.LOGOUT_REDIRECT_URL:
        return redirect(settings.LOGOUT_REDIRECT_URL)

    if settings.HOSTNAME:
        redirect_url = settings.HOSTNAME
        if not redirect_url.endswith('/'):
            redirect_url += '/'
        return redirect(redirect_url)
    return redirect('/')


# Basir: no CSRF check, our backend service signs users up programmatically
@csrf_exempt
def user_signup(request):
    """Sign up page"""
    user = request.user
    next_page = request.GET.get('next')
    token = request.GET.get('token')

    # checks if the URL is a safe redirection.
    if not next_page or not url_has_allowed_host_and_scheme(url=next_page, allowed_hosts=request.get_host()):
        next_page = reverse('main')

    user_form = forms.UserSignupForm()
    organization_form = OrganizationSignupForm()

    if user.is_authenticated:
        return redirect(next_page)

    # make a new user
    if request.method == 'POST':
        # Basir: the user joins the organization of the invite token. The upstream
        # DISABLE_SIGNUP_WITHOUT_LINK / token mismatch / expiry checks are intentionally not applied;
        # a missing or unknown token fails here with Organization.DoesNotExist.
        # Exception: on a fresh install (no organization yet) the first user may sign up without a token;
        # save_user then creates the first organization for them, as upstream does.
        if not token and not Organization.objects.exists():
            organization = None
        else:
            organization = Organization.objects.get(token=token)

        user_form = forms.UserSignupForm(request.POST)
        organization_form = OrganizationSignupForm(request.POST)

        if user_form.is_valid():
            redirect_response = proceed_registration(request, user_form, organization_form, next_page)
            if redirect_response:
                if organization is not None:
                    # Basir: move the new user from the default (first) organization to the token's organization.
                    # The signup form stores the email normalized (stripped, lowercased), so look it up the same way.
                    user = User.objects.get(email=normalize_user_email(request.POST.get('email')))
                    first_organization = Organization.objects.first()
                    first_organization.remove_user(user)
                    organization.add_user(user)
                    user.active_organization = organization
                    user.save(update_fields=['active_organization'])
                return redirect_response

    if flag_set('fflag_feat_front_lsdv_e_297_increase_oss_to_enterprise_adoption_short'):
        return render(
            request,
            'users/new-ui/user_signup.html',
            {
                'user_form': user_form,
                'organization_form': organization_form,
                'next': quote(next_page),
                'token': token,
                'found_us_options': forms.FOUND_US_OPTIONS,
                'elaborate': forms.FOUND_US_ELABORATE,
            },
        )

    return render(
        request,
        'users/user_signup.html',
        {
            'user_form': user_form,
            'organization_form': organization_form,
            'next': quote(next_page),
            'token': token,
        },
    )


# Basir: no CSRF check, our backend service logs in programmatically
@csrf_exempt
def user_login(request):
    """Login page"""
    user = request.user
    next_page = request.GET.get('next')

    # checks if the URL is a safe redirection.
    if not next_page or not url_has_allowed_host_and_scheme(url=next_page, allowed_hosts=request.get_host()):
        next_page = reverse('main')

    login_form = load_func(settings.USER_LOGIN_FORM)
    form = login_form()

    if user.is_authenticated:
        return redirect(next_page)

    if request.method == 'POST':
        form = login_form(request.POST)
        if form.is_valid():
            user = form.cleaned_data['user']
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            if form.cleaned_data['persist_session'] is not True:
                # Set the session to expire when the browser is closed
                request.session['keep_me_logged_in'] = False
                request.session.set_expiry(0)

            # user is organization member
            org_pk = Organization.find_by_user(user).pk
            user.active_organization_id = org_pk
            user.save(update_fields=['active_organization'])
            return redirect(next_page)

    if flag_set('fflag_feat_front_lsdv_e_297_increase_oss_to_enterprise_adoption_short'):
        return render(request, 'users/new-ui/user_login.html', {'form': form, 'next': quote(next_page)})

    return render(request, 'users/user_login.html', {'form': form, 'next': quote(next_page)})


@login_required
def user_account(request, sub_path=None):
    """
    Handle user account view and profile updates.

    This view displays the user's profile information and allows them to update
    it. It requires the user to be authenticated and have an active organization
    or an organization_pk in the session.

    Args:
        request (HttpRequest): The request object.
        sub_path (str, optional): A sub-path parameter for potential URL routing.
            Defaults to None.

    Returns:
        HttpResponse: Renders the user account template with user profile form,
            or redirects to 'main' if no active organization is found,
            or redirects back to user-account after successful profile update.

    Notes:
        - Authentication is required (enforced by @login_required decorator)
        - Retrieves the user's API token for display in the template
        - Form validation happens on POST requests
    """
    user = request.user

    if user.active_organization is None and 'organization_pk' not in request.session:
        return redirect(reverse('main'))

    form = forms.UserProfileForm(instance=user)
    token = Token.objects.get(user=user)

    if request.method == 'POST':
        form = forms.UserProfileForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            return redirect(reverse('user-account'))

    return render(
        request,
        'users/user_account.html',
        {'settings': settings, 'user': user, 'user_profile_form': form, 'token': token},
    )
