from events.utils import create_event


class PageViewMiddleware:
    """
    Middleware to log page view events for all GET requests.
    """

    IGNORED_PATHS = [
        "/favicon.ico",  # Ignorar favicon
        "/favicon.png",  # Variación adicional
        "/"
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only handle GET requests
        if (
            request.method == "GET"
            and request.path not in self.IGNORED_PATHS
            and not request.path.startswith("/api/")
        ):
            user = request.user if request.user.is_authenticated else None
            create_event(
                user=user,
                event_type="page_view",
                description="Page viewed",
                data={"url": request.path},
            )
        response = self.get_response(request)
        return response
