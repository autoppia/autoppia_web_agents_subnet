from django.contrib import admin

# Register your models here.
from pythondjangocrud.apps.position.models import Position
from pythondjangocrud.core.admin import AuditAdminMixin


@admin.register(Position)
class PositionAdmin(AuditAdminMixin, admin.ModelAdmin):
    """
    Admin options for Learning model.
    """
    list_display = ['title','salary']