from access_control.models import AccessGroup, UserAccess
from django.contrib import admin


@admin.register(AccessGroup)
class AccessGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'created_at')
    search_fields = ('name',)
    filter_horizontal = ('projects', 'users')


@admin.register(UserAccess)
class UserAccessAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'keycloak_sub', 'updated_at')
    list_filter = ('role',)
    search_fields = ('user__email', 'keycloak_sub')
    raw_id_fields = ('user',)
