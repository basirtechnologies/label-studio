from django.apps import AppConfig


class AccessControlConfig(AppConfig):
    name = 'access_control'
    verbose_name = 'Access control (Basir DW-907)'

    def ready(self):
        from access_control import permissions

        permissions.install()
