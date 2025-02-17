from events.models import Event


def create_event(user, event_type, description, data=None, web_agent_id=None):
    """
    Create an event in the database.

    Args:
        user (User): The user associated with the event (can be None).
        event_type (str): The type of the event (must be one of Event.EVENT_TYPES).
        description (str): A brief description of the event.
        data (dict): Additional data to store with the event.
    """
    Event.objects.create(
        user=user,
        event_type=event_type,
        description=description,
        data=data or {},  # Use empty dict if no data is provided
        web_agent_id=web_agent_id
    )
