from django.db import models

from pythondjangocrud.apps.users.models import User


class Event(models.Model):
    EVENT_TYPES = [
        ('attendance_create', 'Attendance Created'),
        ('attendance_update', 'Attendance Updated'),
        ('attendance_delete', 'Attendance Deleted'),
        ('department_create', 'Department Created'),
        ('department_update', 'Department Updated'),
        ('department_delete', 'Department Deleted'),
        ('employee_create', 'Employee Created'),
        ('employee_update', 'Employee Updated'),
        ('employee_delete', 'Employee Deleted'),
        ('payroll_create', 'Payroll Created'),
        ('payroll_update', 'Payroll Updated'),
        ('payroll_delete', 'Payroll Deleted'),
        ('position_create', 'Position Created'),
        ('position_update', 'Position Updated'),
        ('position_delete', 'Position Deleted'),
        ('user_view', 'User View'),
        ('user_update', 'User Updated'),
        ('user_redirect', 'User Redirect'),
    ]

    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    description = models.TextField()
    data = models.JSONField(blank=True, null=True)  # JSON field compatible con MySQL
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='events', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    web_agent_id = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"{self.event_type} at {self.created_at} for web_agent {self.web_agent_id}"
