from django.db import models
from django.utils.translation import gettext_lazy as _

# Let models be here
from pythondjangocrud.core.models import AbstractChoice


class Employee(AbstractChoice):
    """
        Model Employee
    """


    id = models.BigAutoField(primary_key=True)
    first_name = models.TextField()
    last_name = models.TextField()
    email = models.TextField()
    hire_date = models.DateField(auto_now = False , auto_now_add = False)

    class Meta:
        db_table = 'employee'
        verbose_name = _('employee')
        verbose_name_plural = _('employee')
        ordering = ['id']

    def __str__(self):
        return f"{self.first_name} {self.last_name}" if self.first_name and self.last_name else "Unnamed Employee"
