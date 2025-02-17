from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from jobsapp.reset_seed import reset_database


@csrf_exempt
def reset_seed(request):
    """Endpoint to reset the database and seed initial data."""
    if request.method == "POST":
        try:
            reset_database()
            return JsonResponse({"status": "success", "message": "Database reset and seeded successfully."}, status=200)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
    return JsonResponse({"status": "error", "message": "Invalid request method."}, status=405)
