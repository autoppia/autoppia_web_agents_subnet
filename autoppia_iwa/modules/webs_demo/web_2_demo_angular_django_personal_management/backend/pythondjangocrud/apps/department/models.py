from django.db import models
from django.utils.translation import gettext_lazy as _
# Let models be here
from pythondjangocrud.core.models import AbstractChoice

class Department(AbstractChoice):
    """
        Model Department
    """


    id = models.BigAutoField(primary_key=True)
    name = models.TextField()
    location = models.TextField()

    class Meta:
        db_table = 'department'
        verbose_name = _('department')
        verbose_name_plural = _('department')
        ordering = ['id']

    def __str__(self):
        return self.name