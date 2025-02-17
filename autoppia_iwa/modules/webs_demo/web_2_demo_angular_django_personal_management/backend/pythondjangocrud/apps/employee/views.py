from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ModelViewSet

from pythondjangocrud.apps.employee.models import Employee
from pythondjangocrud.apps.employee.serializers import EmployeeSerializer
from pythondjangocrud.apps.events.utils import create_event


class EmployeeViewSet(ModelViewSet):
    """
        Viewset EmployeeViewSet
    """
    queryset = Employee.objects.actives()
    serializer_class = EmployeeSerializer
    permission_classes = (AllowAny,)

    def perform_create(self, serializer):
        """
        Override perform_create to log event when an employee record is created.
        """
        # Create the employee record
        employee = serializer.save()

        # Log the event (creating an employee record)
        create_event(
            user=self.request.user,
            event_type='employee_create',
            description=f'Employee record created for {employee.name}',
            data={'employee_id': employee.id, 'name': employee.name},
            web_agent_id=self.request.headers.get("X-WebAgent-Id", None)
        )

    def perform_update(self, serializer):
        """
        Override perform_update to log event when an employee record is updated.
        """
        # Update the employee record
        employee = serializer.save()

        # Log the event (updating an employee record)
        create_event(
            user=self.request.user,
            event_type='employee_update',
            description=f'Employee record updated for {employee.name}',
            data={'employee_id': employee.id, 'name': employee.name},
            web_agent_id=self.request.headers.get("X-WebAgent-Id", None)
        )

    def perform_destroy(self, instance):
        """
        Override perform_destroy to log event when an employee record is deleted.
        """
        # Log the event (deleting an employee record)
        create_event(
            user=self.request.user,
            event_type='employee_delete',
            description=f'Employee record deleted for {instance.name}',
            data={'employee_id': instance.id, 'name': instance.name},
            web_agent_id=self.request.headers.get("X-WebAgent-Id", None)
        )

        # Perform the deletion
        instance.delete()
