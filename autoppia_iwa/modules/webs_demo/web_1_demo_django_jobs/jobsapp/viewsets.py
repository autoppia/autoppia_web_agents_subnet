from rest_framework import viewsets

from .models import Job, Applicant
from .serializers import JobSerializer, ApplicantSerializer


class JobViewSet(viewsets.ModelViewSet):
    """
    A viewset for viewing and editing job instances.
    Provides endpoints:
        - GET /jobs/: Retrieve a list of jobs.
        - POST /jobs/: Create a new job.
        - GET /jobs/{id}/: Retrieve a job by ID.
        - PUT /jobs/{id}/: Update a job by ID.
        - PATCH /jobs/{id}/: Partially update a job by ID.
        - DELETE /jobs/{id}/: Delete a job by ID.
    """
    queryset = Job.objects.all()
    serializer_class = JobSerializer


class ApplicantViewSet(viewsets.ModelViewSet):
    """
    A viewset for viewing and editing applicant instances.
    Provides endpoints:
        - GET /applicants/: Retrieve a list of applicants.
        - POST /applicants/: Create a new applicant.
        - GET /applicants/{id}/: Retrieve an applicant by ID.
        - PUT /applicants/{id}/: Update an applicant by ID.
        - PATCH /applicants/{id}/: Partially update an applicant by ID.
        - DELETE /applicants/{id}/: Delete an applicant by ID.
    """
    queryset = Applicant.objects.all()
    serializer_class = ApplicantSerializer
