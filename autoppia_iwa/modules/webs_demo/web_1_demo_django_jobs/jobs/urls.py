from django.contrib import admin
from django.urls import path, re_path, include
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

schema_view = get_schema_view(
    openapi.Info(
        title="API Docs",
        default_version="v1",
        description="""An Online Job Portal Project in Django is a platform for job seekers to find appropriate jobs while companies can publish their vacancies and find good candidates.

Jobseekers can:
1. Post their resumes.
2. Browse for job searches.
3. View personal work listings.

Companies can:
1. Post job details and vacancies.
2. Scan applicant resumes.

Example Workflow to Create a User:
1. Navigate to the registration endpoint: POST /users/
2. Provide the necessary information (username, email, password, etc.).
3. Submit the form to create a new user account.
""",
        terms_of_service="https://www.example.com/terms/",
        contact=openapi.Contact(email="contact@example.com"),
        license=openapi.License(name="BSD License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("jobsapp.urls")),
    path("", include("accounts.urls")),
    path(
        "api/", include("events.urls")
    ),  # Incluye las URLs de la aplicación de eventos
    re_path(
        r"^swagger(?P<format>\.json|\.yaml)$",
        schema_view.without_ui(cache_timeout=0),
        name="schema-json",
    ),
    path(
        "swagger/",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
]
