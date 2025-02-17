from django.db import models
from django.utils.translation import gettext_lazy as _
# Let models be here
from pythondjangocrud.core.models import AbstractChoice

class Position(AbstractChoice):
    """
        Model Position
    """


    id = models.BigAutoField(primary_key=True)
    title = models.TextField()
    salary = models.FloatField()

    class Meta:
        db_table = 'position'
        verbose_name = _('position')
        verbose_name_plural = _('position')
        ordering = ['id']

    def __str__(self):
        return self.title