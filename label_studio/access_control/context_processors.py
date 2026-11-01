"""Basir DW-907: the user's LS role for the page (window.APP_SETTINGS.user.ls_access), so the UI can hide
admin-only entries for labelers. The server enforces the rules either way."""

from access_control import access


def ls_access(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    return {'ls_access': access.ls_access_info(user)}
