from django.contrib import admin

# Register your models here.
from pythondjangocrud.apps.employee.models import Employee
from pythondjangocrud.core.admin import AuditAdminMixin


@admin.register(Employee)
class EmployeeAdmin(AuditAdminMixin, admin.ModelAdmin):
    """
    Admin options for Learning model.
    """
    list_display = ['first_name','last_name','email','hire_date']