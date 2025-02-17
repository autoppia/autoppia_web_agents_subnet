from django.db import models

from accounts.models import User  # Import your custom user model


class Event(models.Model):
    EVENT_TYPES = [
        ('registration', 'User Registration'),
        ('login', 'User Login'),
        ('logout', 'User Logout'),
        ('password_change', 'Password Change'),
        ('profile_update', 'Profile Update'),
        ('job_application', 'Job Application'),
        ('job_post_creation', 'Job Post Creation'),
        ('job_post_update', 'Job Post Update'),
        ('job_post_deletion', 'Job Post Deletion'),
        ('resume_upload', 'Resume Upload'),
        ('newsletter_subscription', 'Newsletter Subscription'),
        ('newsletter_unsubscription', 'Newsletter Unsubscription'),
        ('message_sent', 'Message Sent'),
        ('message_received', 'Message Received'),
        ('page_view', 'Page View'),
        ('search', 'Search'),
    ]

    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    description = models.TextField()
    data = models.JSONField(blank=True, null=True)  # JSON field compatible con MySQL
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='events', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    web_agent_id = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"{self.event_type} at {self.created_at} for web_agent {self.web_agent_id}"
