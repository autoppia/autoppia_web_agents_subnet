from django.urls import path, include

from rest_framework.routers import DefaultRouter

# Djangp REST JWT
from rest_framework_jwt.views import obtain_jwt_token, refresh_jwt_token, verify_jwt_token

router = DefaultRouter()
app_name = "api"

urlpatterns = [
    path('', include(('pythondjangocrud.apps.users.urls', 'users'), namespace='users')),
    path('', include(('pythondjangocrud.apps.employee.urls', 'employee'), namespace='employee')),
    path('', include(('pythondjangocrud.apps.department.urls', 'department'), namespace='department')),
    path('', include(('pythondjangocrud.apps.position.urls', 'position'), namespace='position')),
    path('', include(('pythondjangocrud.apps.attendance.urls', 'attendance'), namespace='attendance')),
    path('', include(('pythondjangocrud.apps.payroll.urls', 'payroll'), namespace='payroll')),

    # Urls JWT
    path('auth/token-auth/', obtain_jwt_token),
    path('auth/token-refresh/', refresh_jwt_token),
    path('auth/token-verify/', verify_jwt_token),
] + router.urls
