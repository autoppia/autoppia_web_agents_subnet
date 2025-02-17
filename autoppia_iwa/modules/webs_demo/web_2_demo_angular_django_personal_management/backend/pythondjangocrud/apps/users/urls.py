# Django
from django.urls import path, include

# Django REST Framework
from rest_framework.routers import DefaultRouter

# Views
from .api import views as user_views

app_name = "users"

router = DefaultRouter()
router.register(r'users', user_views.UserViewSet, basename='users')

urlpatterns = router.urls
