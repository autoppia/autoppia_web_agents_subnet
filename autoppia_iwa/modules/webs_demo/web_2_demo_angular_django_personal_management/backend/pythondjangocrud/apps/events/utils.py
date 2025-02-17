from django.contrib.auth.models import User

from pythondjangocrud.apps.events.models import Event


def create_event(user, event_type, description, data=None, web_agent_id=None):
    """
    Create an event in the database.

    Args:
        user (User or None): The user associated with the event (can be None).
        event_type (str): The type of the event (must be one of Event.EVENT_TYPES).
        description (str): A brief description of the event.
        data (dict, optional): Additional data to store with the event. Defaults to an empty dictionary.
        web_agent_id (int, optional): The web_agent ID associated with the event. Defaults to None.
    """

    # Create the event
    Event.objects.create(
        user=user if isinstance(user, User) else None,
        event_type=event_type,
        description=description,
        data=data or {},
        web_agent_id=web_agent_id
    )
