from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PositionConfig(AppConfig):
    name = "pythondjangocrud.apps.position"
    verbose_name = _("Position")

    def ready(self):
        try:
            import pythondjangocrud.apps.position.signals  # noqa F401
        except ImportError:
            pass
