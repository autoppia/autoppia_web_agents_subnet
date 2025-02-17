from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ModelViewSet

from pythondjangocrud.apps.events.utils import create_event
from pythondjangocrud.apps.position.models import Position
from pythondjangocrud.apps.position.serializers import PositionSerializer


class PositionViewSet(ModelViewSet):
    """
        Viewset PositionViewSet
    """
    queryset = Position.objects.actives()
    serializer_class = PositionSerializer
    permission_classes = (AllowAny,)

    def perform_create(self, serializer):
        """
        Override perform_create to log event when a position record is created.
        """
        # Create the position record
        position = serializer.save()

        # Log the event (creating a position record)
        create_event(
            user=self.request.user,
            event_type='position_create',
            description=f'Position record created for {position.title}',
            data={'position_id': position.id, 'title': position.title},
            web_agent_id=self.request.headers.get("X-WebAgent-Id", None)
        )

    def perform_update(self, serializer):
        """
        Override perform_update to log event when a position record is updated.
        """
        # Update the position record
        position = serializer.save()

        # Log the event (updating a position record)
        create_event(
            user=self.request.user,
            event_type='position_update',
            description=f'Position record updated for {position.title}',
            data={'position_id': position.id, 'title': position.title},
            web_agent_id=self.request.headers.get("X-WebAgent-Id", None)

        )

    def perform_destroy(self, instance):
        """
        Override perform_destroy to log event when a position record is deleted.
        """
        # Log the event (deleting a position record)
        create_event(
            user=self.request.user,
            event_type='position_delete',
            description=f'Position record deleted for {instance.title}',
            data={'position_id': instance.id, 'title': instance.title},
            web_agent_id=self.request.headers.get("X-WebAgent-Id", None)
        )

        # Perform the deletion
        instance.delete()
