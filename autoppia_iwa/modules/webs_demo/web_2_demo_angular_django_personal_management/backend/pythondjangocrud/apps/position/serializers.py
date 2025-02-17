from rest_framework import serializers
from .models import Position
from ...core.serializers import AuditSerializerMixin


class PositionSerializer(serializers.ModelSerializer):
    """
        Serializer position
    """
    class Meta(AuditSerializerMixin.Meta):
        model = Position
