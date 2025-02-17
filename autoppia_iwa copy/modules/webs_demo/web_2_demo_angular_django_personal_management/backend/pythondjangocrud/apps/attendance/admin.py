from django.contrib import admin

# Register your models here.
from pythondjangocrud.apps.attendance.models import Attendance
from pythondjangocrud.core.admin import AuditAdminMixin


@admin.register(Attendance)
class AttendanceAdmin(AuditAdminMixin, admin.ModelAdmin):
    """
    Admin options for Learning model.
    """
    list_display = ['employee_id','date','status']