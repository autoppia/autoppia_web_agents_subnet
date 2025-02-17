from rest_framework import serializers
from .models import Attendance
from ...core.serializers import AuditSerializerMixin


class AttendanceSerializer(serializers.ModelSerializer):
    """
        Serializer attendance
    """
    class Meta(AuditSerializerMixin.Meta):
        model = Attendance
