from django.urls import path
from keycloak_auth import views

# the URL names mozilla-django-oidc looks up
urlpatterns = [
    path('oidc/authenticate/', views.KeycloakLoginView.as_view(), name='oidc_authentication_init'),
    path('oidc/callback/', views.KeycloakCallbackView.as_view(), name='oidc_authentication_callback'),
]
