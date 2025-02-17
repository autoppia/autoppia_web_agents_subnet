from django.db import models

class CoreManager(models.Manager):
    def actives(self):
        return super(CoreManager, self).get_queryset().filter(is_active=True)
