from crum import get_current_user
from django.db import models
from django.utils.translation import gettext_lazy as _

from pythondjangocrud.core.models import CoreManager


class AbstractAudit(models.Model):
    """
    An abstract model that manages the modifications made to a model
    """
    is_active = models.BooleanField(
        _('active'),
        default=True,
        help_text=_(
            'Designates whether this record should be treated as active. '
            'Unselect this instead of deleting accounts.'
        ),
    )
    creation_date = models.DateTimeField(
        _('creation date'),
        auto_now_add=True,
        help_text=_('record creation date')
    )
    created_by = models.CharField(
        _('username created'),
        max_length=100,  # max length of User.username
        help_text=_('username that created the record')
    )
    update_date = models.DateTimeField(
        _('update date'),
        auto_now=True,
        help_text=_('record update date')
    )

    update_by = models.CharField(
        _('username updated'),
        max_length=100,  # max length of User.username
        help_text=_('username that updated the record')
    )

    objects = CoreManager()

    class Meta:
        abstract = True

    def get_current_username(self):
        """
        gets the user who logs in or returns the user system
        :return: username
        """
        user = get_current_user()
        if user and user.is_authenticated:
            return getattr(user, user.USERNAME_FIELD, 'system')
        return 'system'

    def set_created_by(self):
        if self.pk is None:
            self.created_by = self.get_current_username()

    def set_update_by(self):
        self.update_by = self.get_current_username()

    def save(self, *args, **kwargs):
        self.set_created_by()
        self.set_update_by()
        super(AbstractAudit, self).save(*args, **kwargs)


class AbstractChoice(AbstractAudit):
    """
    An abstract model for and id and name entry (i.e. field).
    """
    name = models.CharField(
        _('name'),
        max_length=200,
        blank=True,
        null=True,
        default=None,
        help_text=_("Name of the choice."),
    )
    code = models.CharField(
        _('code'),
        max_length=20,
        blank=True,
        null=True,
        default=None,
        help_text=_("Code."),
    )

    class Meta:
        abstract = True

    def __str__(self):
        return "{} - {}".format(self.id, self.name)


class AbstractAttachment(AbstractAudit):
    title = models.CharField(max_length=90, null=True, blank=True)
    category = models.CharField(max_length=90, null=True, blank=True)
    description = models.CharField(max_length=90, null=True, blank=True)

    class Meta:
        abstract = True

    def __str__(self):
        return "{} - {}".format(self.id, self.title)
