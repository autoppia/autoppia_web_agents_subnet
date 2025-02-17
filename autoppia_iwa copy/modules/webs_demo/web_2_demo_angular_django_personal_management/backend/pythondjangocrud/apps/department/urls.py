from rest_framework.routers import DefaultRouter

from pythondjangocrud.apps.department.views import DepartmentViewSet

app_name = "department"

router = DefaultRouter()
router.register(r'department', DepartmentViewSet)

urlpatterns = router.urls
