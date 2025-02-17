from rest_framework import status
from rest_framework.decorators import api_view
# from rest_framework.decorators import api_view, permission_classes
# from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Event
from .serializers import EventSerializer


@api_view(["GET"])
def get_events(request):
    """
    Fetch events for the web_agent identified by the provided `web_agent_id`.
    """
    web_agent_id = request.headers.get("X-WebAgent-Id")  # Retrieve web_agent_id from query params
    if not web_agent_id:
        return Response({"error": "X-WebAgent-Id is required."}, status=status.HTTP_400_BAD_REQUEST)

    events = Event.objects.filter(web_agent_id=web_agent_id).order_by("-created_at")
    serializer = EventSerializer(events, many=True)
    return Response(serializer.data)


@api_view(["GET"])
# @permission_classes([IsAuthenticated])
def my_events(request):
    """
    Get all my events
    """
    # user = request.user
    # user_email = request.data.get("user_email")
    # user = User.objects.get(email=user_email)
    events = Event.objects.order_by("-created_at")
    serializer = EventSerializer(events, many=True)
    return Response(serializer.data)


@api_view(["DELETE"])
def reset_events(request):
    """
    Delete Events
    """
    web_agent_id = request.headers.get("X-WebAgent-Id")
    if not web_agent_id:
        return Response({"error": "X-WebAgent-Id is required."}, status=status.HTTP_400_BAD_REQUEST)

    Event.objects.filter(web_agent_id=web_agent_id).delete()
    return Response(
        {"message": f"Events for web_agent '{web_agent_id}' have been deleted successfully."},
        status=status.HTTP_204_NO_CONTENT,
    )


@api_view(["POST"])
def add_event(request):
    """
    Add a new event to the database.

    Expected JSON payload:
    {
        "web_agent_id": "example-webAgent-id",
        "event_type": "example-event-type",
        "event_data": { ... }  # JSON object with event-specific data
    }
    """
    serializer = EventSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
