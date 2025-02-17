from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class EmployeeConfig(AppConfig):
    name = "pythondjangocrud.apps.employee"
    verbose_name = _("Employee")

    def ready(self):
        try:
            import pythondjangocrud.apps.employee.signals  # noqa F401
        except ImportError:
            pass
