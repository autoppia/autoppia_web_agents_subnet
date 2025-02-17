from rest_framework.routers import DefaultRouter

from pythondjangocrud.apps.payroll.views import PayrollViewSet

app_name = "payroll"

router = DefaultRouter()
router.register(r'payroll', PayrollViewSet)

urlpatterns = router.urls
