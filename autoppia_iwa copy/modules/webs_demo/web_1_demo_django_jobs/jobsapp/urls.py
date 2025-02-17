from django.urls import path, include
from django.views.generic.base import RedirectView
from rest_framework.routers import DefaultRouter

from .views import ApplyJobView, JobListView, JobDetailsView, AboutView
from .views.employer import DashboardView, ApplicantsListView, ApplicantPerJobView, filled, JobCreateView
from .views.home import HomeView, SearchView, ContactView
from .views.reset_events import reset_seed
from .viewsets import JobViewSet, ApplicantViewSet

app_name = "jobs"

router = DefaultRouter()
router.register(r'jobs', JobViewSet)
router.register(r'applicants', ApplicantViewSet)

urlpatterns = [
    path('', RedirectView.as_view(url='/home', permanent=True), name='redirect-to-home'),  # Redirige / a /home
    path('home', HomeView.as_view(), name='home'), path('search', SearchView.as_view(), name='search'),
    path('contact/', ContactView.as_view(), name='contact'),
    path('about/', AboutView.as_view(), name='about'),
    path("reset_seed/", reset_seed, name="reset_seed"),
    path('employer/dashboard', include([
        path('', DashboardView.as_view(), name='employer-dashboard'),
        path('all-applicants', ApplicantsListView.as_view(), name='employer-all-applicants'),
        path('applicants/<int:job_id>', ApplicantPerJobView.as_view(), name='employer-dashboard-applicants'),
        path('mark-filled/<int:job_id>', filled, name='job-mark-filled'),
    ])),
    path('apply-job/<int:job_id>', ApplyJobView.as_view(), name='apply-job'),
    path('jobs', JobListView.as_view(), name='jobs'),
    path('jobs/<int:id>', JobDetailsView.as_view(), name='jobs-detail'),
    path('employer/jobs/create', JobCreateView.as_view(), name='employer-jobs-create'),
    path('api/', include(router.urls)),
]
