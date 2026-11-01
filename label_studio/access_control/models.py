"""Basir DW-907: device-based access control.

Access between devices is modelled with access groups (e.g. ``ls-sightence-male``): a project has one or more
groups, a user has zero or more groups plus an LS role. Everything lives in this app's own tables, so the fork
adds no migrations to the upstream apps (users, projects) and an upgraded 1.17 database only gets new tables.
"""

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

ACCESS_GROUP_NAME_REGEX = r'^[A-Za-z0-9][A-Za-z0-9_.\-]*$'
access_group_name_validator = RegexValidator(
    ACCESS_GROUP_NAME_REGEX,
    _('Use letters, digits, "-", "_" and "." only, starting with a letter or digit (e.g. ls-sightence-male).'),
)


class LSRole(models.TextChoices):
    ADMIN = 'admin', _('LS admin')
    LABELER = 'labeler', _('LS labeler')


class AccessGroup(models.Model):
    """A named access group, e.g. ``ls-sightence-male``. Groups are created on first use, not hard-coded."""

    name = models.CharField(
        _('name'), max_length=150, unique=True, validators=[access_group_name_validator], help_text='Group name'
    )
    description = models.TextField(_('description'), blank=True, default='')
    projects = models.ManyToManyField(
        'projects.Project',
        related_name='access_groups',
        blank=True,
        help_text='Projects in this group',
    )
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='access_groups',
        blank=True,
        help_text='Users in this group',
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class UserAccess(models.Model):
    """LS role of a user and, for Keycloak users, the Keycloak subject (PR DW-908)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ls_access',
        primary_key=True,
    )
    role = models.CharField(
        _('LS role'),
        max_length=16,
        choices=LSRole.choices,
        null=True,
        blank=True,
        help_text='admin: sees and manages everything; labeler: sees only projects sharing an access group',
    )
    keycloak_sub = models.CharField(
        _('Keycloak subject'),
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        help_text='Keycloak "sub" claim of the user; empty for local accounts',
    )
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    def __str__(self):
        return f'{self.user_id}: {self.role or "no role"}'
