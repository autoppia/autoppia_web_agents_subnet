from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PayrollConfig(AppConfig):
    name = "pythondjangocrud.apps.payroll"
    verbose_name = _("Payroll")

    def ready(self):
        try:
            import pythondjangocrud.apps.payroll.signals  # noqa F401
        except ImportError:
            pass
