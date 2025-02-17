from django.db import models
from django.utils.translation import gettext_lazy as _
# Let models be here
from pythondjangocrud.core.models import AbstractChoice
from pythondjangocrud.apps.employee.models import Employee

class Attendance(AbstractChoice):
    """
        Model Attendance
    """


    id = models.BigAutoField(primary_key=True)
    date = models.DateField(auto_now = False , auto_now_add = False)
    status = models.TextField()
    employee_id = models.ForeignKey(Employee, related_name="attendance",
      on_delete=models.SET_NULL, blank=True, null=True, default=None,)

    class Meta:
        db_table = 'attendance'
        verbose_name = _('attendance')
        verbose_name_plural = _('attendance')
        ordering = ['id']

    def __str__(self):
        return self.employee_id