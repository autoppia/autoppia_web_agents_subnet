from rest_framework import serializers
from .models import Employee
from ...core.serializers import AuditSerializerMixin


class EmployeeSerializer(serializers.ModelSerializer):
    """
        Serializer employee
    """
    class Meta(AuditSerializerMixin.Meta):
        model = Employee
