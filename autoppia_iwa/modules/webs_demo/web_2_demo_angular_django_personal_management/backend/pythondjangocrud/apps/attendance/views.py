from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ModelViewSet

from pythondjangocrud.apps.attendance.models import Attendance
from pythondjangocrud.apps.attendance.serializers import AttendanceSerializer
from pythondjangocrud.apps.events.utils import create_event

class AttendanceViewSet(ModelViewSet):
    """
        Viewset AttendanceViewSet
    """
    queryset = Attendance.objects.actives()
    serializer_class = AttendanceSerializer
    permission_classes = (AllowAny,)

    def perform_create(self, serializer):
        """
        Override perform_create to log event when an attendance record is created.
        """
        # Create the attendance record
        attendance = serializer.save()

        # Log the event (creating an attendance record)
        create_event(
            user=self.request.user,
            event_type='attendance_create',
            description=f'Attendance record created for {attendance.employee_id.first_name} on {attendance.date.isoformat()}',
            data={'attendance_id': attendance.id, 'user': attendance.employee_id.id, 'date': attendance.date.isoformat()},
            miner_id=self.request.headers.get("X-Miner-Id", None)
        )

    def perform_update(self, serializer):
        """
        Override perform_update to log event when an attendance record is updated.
        """
        # Update the attendance record
        attendance = serializer.save()

        # Log the event (updating an attendance record)
        create_event(
            user=self.request.user,
            event_type='attendance_update',  # Define event type
            description=f'Attendance record updated for {attendance.employee_id.first_name} on {attendance.date.isoformat()}',
            data={'attendance_id': attendance.id, 'user': attendance.employee_id.id, 'date': attendance.date.isoformat()},
            miner_id=self.request.headers.get("X-Miner-Id", None)
        )

    def perform_destroy(self, instance):
        """
        Override perform_destroy to log event when an attendance record is deleted.
        """
        # Log the event (deleting an attendance record)
        create_event(
            user=self.request.user,
            event_type='attendance_delete',
            description=f'Attendance record deleted for {instance.employee_id.first_name} on {instance.date.isoformat()}',
            data={'attendance_id': instance.id, 'user': instance.employee_id.id, 'date': instance.date.isoformat()},
            miner_id=self.request.headers.get("X-Miner-Id", None)
        )

        # Perform the deletion
        instance.delete()
