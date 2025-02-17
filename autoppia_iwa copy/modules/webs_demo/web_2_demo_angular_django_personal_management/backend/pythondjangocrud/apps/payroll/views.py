from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ModelViewSet

from pythondjangocrud.apps.payroll.models import Payroll
from pythondjangocrud.apps.payroll.serializers import PayrollSerializer
from pythondjangocrud.apps.events.utils import create_event

class PayrollViewSet(ModelViewSet):
    """
    Viewset for Payroll, with event logging for create, update, and delete.
    """
    queryset = Payroll.objects.actives()
    serializer_class = PayrollSerializer
    permission_classes = (AllowAny,)

    def perform_create(self, serializer):
        """
        Override perform_create to log event when a payroll record is created.
        """
        # Create the payroll record
        payroll = serializer.save()

        # Log the event (creating a payroll record)
        create_event(
            user=self.request.user,
            event_type='payroll_create',
            description=f'Payroll record created for employee {payroll.employee_id.first_name}',
            data={'payroll_id': payroll.id, 'employee_id': payroll.employee_id.id, 'amount': payroll.amount}  ,
            miner_id=self.request.headers.get("X-Miner-Id", None)
        )

    def perform_update(self, serializer):
        """
        Override perform_update to log event when a payroll record is updated.
        """
        # Update the payroll record
        payroll = serializer.save()

        # Log the event (updating a payroll record)
        create_event(
            user=self.request.user,
            event_type='payroll_update',
            description=f'Payroll record updated for employee {payroll.employee_id.first_name}',
            data={'payroll_id': payroll.id, 'employee_id': payroll.employee_id.id, 'amount': payroll.amount} ,
            miner_id=self.request.headers.get("X-Miner-Id", None)
        )

    def perform_destroy(self, instance):
        """
        Override perform_destroy to log event when a payroll record is deleted.
        """
        # Log the event (deleting a payroll record)
        create_event(
            user=self.request.user,
            event_type='payroll_delete',
            description=f'Payroll record deleted for employee {instance.employee_id.first_name}',
            data={'payroll_id': instance.id, 'employee_id': instance.employee_id.id, 'amount': instance.amount} ,
            miner_id=self.request.headers.get("X-Miner-Id", None)
        )

        # Perform the deletion
        instance.delete()
