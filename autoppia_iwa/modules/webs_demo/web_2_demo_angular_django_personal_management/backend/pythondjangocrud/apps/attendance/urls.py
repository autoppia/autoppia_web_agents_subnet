from rest_framework.routers import DefaultRouter

from pythondjangocrud.apps.attendance.views import AttendanceViewSet

app_name = "attendance"

router = DefaultRouter()
router.register(r'attendance', AttendanceViewSet)

urlpatterns = router.urls
