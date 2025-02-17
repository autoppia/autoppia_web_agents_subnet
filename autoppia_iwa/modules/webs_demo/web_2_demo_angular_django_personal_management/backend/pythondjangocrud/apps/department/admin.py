from django.contrib import admin

# Register your models here.
from pythondjangocrud.apps.department.models import Department
from pythondjangocrud.core.admin import AuditAdminMixin


@admin.register(Department)
class DepartmentAdmin(AuditAdminMixin, admin.ModelAdmin):
    """
    Admin options for Learning model.
    """
    list_display = ['name','location']