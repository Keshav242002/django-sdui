from django.apps import AppConfig


class FlagsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.flags"

    def ready(self):
        import apps.flags.signals  # noqa: F401
