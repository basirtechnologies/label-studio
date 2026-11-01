"""Basir DW-907: admin endpoints to read and set users' LS roles and access groups.

These always require the LS admin role (also while access control is off): otherwise anyone could give
themselves the admin role before access control is switched on. Bootstrap the first admin with
``python manage.py basir_set_user_access --email <email> --role admin``.
"""

from access_control import access
from access_control.models import AccessGroup
from access_control.serializers import AccessGroupSerializer, UserAccessSerializer
from access_control.services import UNSET, set_user_access
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.permissions import BasePermission
from users.models import User


class IsLSAdmin(BasePermission):
    message = 'Only LS admins can manage access groups and roles.'

    def has_permission(self, request, view):
        return access.is_ls_admin(request.user)


class _AdminAPIMixin:
    permission_classes = [*generics.GenericAPIView.permission_classes, IsLSAdmin]


@extend_schema(tags=['Access control'], summary='List access groups')
class AccessGroupListAPI(_AdminAPIMixin, generics.ListAPIView):
    serializer_class = AccessGroupSerializer
    pagination_class = None

    def get_queryset(self):
        return AccessGroup.objects.annotate(
            project_count=Count('projects', distinct=True), user_count=Count('users', distinct=True)
        ).order_by('name')


def _org_users(request):
    return (
        User.objects.filter(
            om_through__organization_id=request.user.active_organization_id, om_through__deleted_at__isnull=True
        )
        .select_related('ls_access')
        .prefetch_related('access_groups')
        .distinct()
        .order_by('email')
    )


@extend_schema(tags=['Access control'], summary='List users with their LS role and access groups')
class UserAccessListAPI(_AdminAPIMixin, generics.ListAPIView):
    serializer_class = UserAccessSerializer
    pagination_class = None

    def get_queryset(self):
        return _org_users(self.request)


@extend_schema(tags=['Access control'], summary="Get or set a user's LS role and access groups")
class UserAccessAPI(_AdminAPIMixin, generics.RetrieveUpdateAPIView):
    serializer_class = UserAccessSerializer
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_queryset(self):
        return _org_users(self.request)

    def perform_update(self, serializer):
        data = serializer.validated_data
        try:
            set_user_access(
                serializer.instance,
                role=data['role'] if 'role' in data else UNSET,
                groups=data['access_groups'] if 'access_groups' in data else UNSET,
            )
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        # re-read: the role/groups are not fields of the User model
        response.data = self.get_serializer(self.get_queryset().get(pk=kwargs['pk'])).data
        return response
