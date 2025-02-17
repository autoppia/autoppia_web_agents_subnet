from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AttendanceConfig(AppConfig):
    name = "pythondjangocrud.apps.attendance"
    verbose_name = _("Attendance")

    def ready(self):
        try:
            import pythondjangocrud.apps.attendance.signals  # noqa F401
        except ImportError:
            pass
