from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DepartmentConfig(AppConfig):
    name = "pythondjangocrud.apps.department"
    verbose_name = _("Department")

    def ready(self):
        try:
            import pythondjangocrud.apps.department.signals  # noqa F401
        except ImportError:
            pass
