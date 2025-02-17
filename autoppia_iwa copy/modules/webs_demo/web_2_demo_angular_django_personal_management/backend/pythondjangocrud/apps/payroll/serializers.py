from rest_framework import serializers
from .models import Payroll
from ...core.serializers import AuditSerializerMixin


class PayrollSerializer(serializers.ModelSerializer):
    """
        Serializer payroll
    """
    class Meta(AuditSerializerMixin.Meta):
        model = Payroll
