from rest_framework import serializers
from .models import Department
from ...core.serializers import AuditSerializerMixin


class DepartmentSerializer(serializers.ModelSerializer):
    """
        Serializer department
    """
    class Meta(AuditSerializerMixin.Meta):
        model = Department
