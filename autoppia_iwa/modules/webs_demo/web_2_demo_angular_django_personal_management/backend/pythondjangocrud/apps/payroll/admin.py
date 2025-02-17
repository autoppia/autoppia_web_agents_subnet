from django.contrib import admin

# Register your models here.
from pythondjangocrud.apps.payroll.models import Payroll
from pythondjangocrud.core.admin import AuditAdminMixin


@admin.register(Payroll)
class PayrollAdmin(AuditAdminMixin, admin.ModelAdmin):
    """
    Admin options for Learning model.
    """
    list_display = ['employee_id','pay_date','amount']