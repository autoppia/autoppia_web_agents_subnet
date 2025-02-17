from django.db import models
from django.utils.translation import gettext_lazy as _
# Let models be here
from pythondjangocrud.core.models import AbstractChoice
from pythondjangocrud.apps.employee.models import Employee

class Payroll(AbstractChoice):
    """
        Model Payroll
    """


    id = models.BigAutoField(primary_key=True)
    pay_date = models.DateField(auto_now = False , auto_now_add = False)
    amount = models.FloatField()
    employee_id = models.ForeignKey(Employee, related_name="payroll",
      on_delete=models.SET_NULL, blank=True, null=True, default=None,)

    class Meta:
        db_table = 'payroll'
        verbose_name = _('payroll')
        verbose_name_plural = _('payroll')
        ordering = ['id']

    def __str__(self):
        return self.employee_id