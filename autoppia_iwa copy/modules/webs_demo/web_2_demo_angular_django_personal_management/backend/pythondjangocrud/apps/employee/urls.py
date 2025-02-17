from rest_framework.routers import DefaultRouter

from pythondjangocrud.apps.employee.views import EmployeeViewSet

app_name = "employee"

router = DefaultRouter()
router.register(r'employee', EmployeeViewSet)

urlpatterns = router.urls
