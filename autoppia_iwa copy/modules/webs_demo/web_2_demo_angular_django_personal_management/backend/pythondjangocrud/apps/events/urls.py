from django.urls import path

from .views import *

urlpatterns = [
    path("events/list/", get_events, name="event-list"),
    path("events/my/", my_events, name="my_events"),
    path("events/reset/", reset_events, name="reset_events"),
    path("events/add/", add_event, name="add_events"),
]
