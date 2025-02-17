from rest_framework.routers import DefaultRouter

from pythondjangocrud.apps.position.views import PositionViewSet

app_name = "position"

router = DefaultRouter()
router.register(r'position', PositionViewSet)

urlpatterns = router.urls
