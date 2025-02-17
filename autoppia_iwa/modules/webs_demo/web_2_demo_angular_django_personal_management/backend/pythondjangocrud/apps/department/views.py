from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ModelViewSet

from pythondjangocrud.apps.department.models import Department
from pythondjangocrud.apps.department.serializers import DepartmentSerializer
from pythondjangocrud.apps.events.utils import create_event


class DepartmentViewSet(ModelViewSet):
    """
        Viewset DepartmentViewSet
    """
    queryset = Department.objects.actives()
    serializer_class = DepartmentSerializer
    permission_classes = (AllowAny,)

    def perform_create(self, serializer):
        """
        Override perform_create to log event when a department record is created.
        """
        # Create the department record
        department = serializer.save()

        # Log the event (creating a department record)
        create_event(
            user=self.request.user,
            event_type='department_create',
            description=f'Department record created for {department.name}',
            data={'department_id': department.id, 'name': department.name},
            web_agent_id=self.request.headers.get("X-WebAgent-Id", None)
        )

    def perform_update(self, serializer):
        """
        Override perform_update to log event when a department record is updated.
        """
        # Update the department record
        department = serializer.save()

        # Log the event (updating a department record)
        create_event(
            user=self.request.user,
            event_type='department_update',
            description=f'Department record updated for {department.name}',
            data={'department_id': department.id, 'name': department.name},
            web_agent_id=self.request.headers.get("X-WebAgent-Id", None)
        )

    def perform_destroy(self, instance):
        """
        Override perform_destroy to log event when a department record is deleted.
        """
        # Log the event (deleting a department record)
        create_event(
            user=self.request.user,
            event_type='department_delete',
            description=f'Department record deleted for {instance.name}',
            data={'department_id': instance.id, 'name': instance.name},
            web_agent_id=self.request.headers.get("X-WebAgent-Id", None)
        )

        # Perform the deletion
        instance.delete()
