"""Basir DW-907: serializers for access groups and LS roles."""

from access_control import access
from access_control.access import ls_access_info
from access_control.models import AccessGroup, LSRole
from access_control.permissions import ADMIN_ONLY_PERMISSIONS
from access_control.services import normalize_group_names
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from users.models import User
from users.serializers import BaseWhoAmIUserSerializer


class AccessGroupNamesField(serializers.ListField):
    """A list of access group names, e.g. ["ls-sightence-male"]. Unknown names create the group."""

    child = serializers.CharField(max_length=150)

    def to_internal_value(self, data):
        names = super().to_internal_value(data)
        try:
            return normalize_group_names(names)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)


class AccessGroupSerializer(serializers.ModelSerializer):
    project_count = serializers.IntegerField(read_only=True)
    user_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AccessGroup
        fields = ['id', 'name', 'description', 'project_count', 'user_count', 'created_at']
        read_only_fields = ['id', 'created_at']


class UserAccessSerializer(serializers.ModelSerializer):
    """A user's LS role and access groups (GET / PATCH /api/access-control/users/<id>/)."""

    # role and access_groups are not User fields: written by the view, added by to_representation
    role = serializers.ChoiceField(
        choices=LSRole.choices, allow_null=True, required=False, write_only=True, help_text='admin, labeler or null'
    )
    access_groups = AccessGroupNamesField(
        required=False, write_only=True, help_text='Access group names (replaces the list)'
    )

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'is_active', 'role', 'access_groups']
        read_only_fields = ['id', 'email', 'first_name', 'last_name', 'is_active']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        record = getattr(instance, 'ls_access', None)  # reverse one-to-one: missing row -> None
        data['role'] = record.role if record else None
        data['keycloak_sub'] = record.keycloak_sub if record else None
        data['access_groups'] = sorted(group.name for group in instance.access_groups.all())
        return data


class LSAccessWhoAmIUserSerializer(BaseWhoAmIUserSerializer):
    """whoami + the LS role, so the UI can hide admin-only entries for labelers (settings.WHOAMI_USER_SERIALIZER)."""

    ls_access = serializers.SerializerMethodField()

    class Meta(BaseWhoAmIUserSerializer.Meta):
        fields = BaseWhoAmIUserSerializer.Meta.fields + ('ls_access',)

    def get_permissions(self, user) -> list[str]:
        permissions = super().get_permissions(user)
        if access.is_restricted(user):
            permissions = [perm for perm in permissions if perm not in ADMIN_ONLY_PERMISSIONS]
        return permissions

    def get_ls_access(self, user) -> dict:
        return ls_access_info(user)
