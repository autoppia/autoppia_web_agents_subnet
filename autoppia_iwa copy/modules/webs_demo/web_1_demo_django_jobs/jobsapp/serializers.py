from rest_framework import serializers

from .models import Job, Applicant


class JobSerializer(serializers.ModelSerializer):
    """
    Serializer for Job model.
    Fields:
        - id: Integer, unique identifier for the job.
        - title: String, title of the job.
        - description: Text, detailed description of the job.
        - location: String, location where the job is based.
        - salary: Decimal, salary for the job.
        - created_at: DateTime, timestamp when the job was created.
        - updated_at: DateTime, timestamp when the job was last updated.
        - user: ForeignKey, reference to the employer who posted the job.
    """

    class Meta:
        model = Job
        fields = '__all__'


class ApplicantSerializer(serializers.ModelSerializer):
    """
    Serializer for Applicant model.
    Fields:
        - id: Integer, unique identifier for the applicant.
        - job: ForeignKey, reference to the job being applied for.
        - user: ForeignKey, reference to the user applying for the job.
        - resume: File, resume of the applicant.
        - cover_letter: Text, cover letter from the applicant.
        - applied_at: DateTime, timestamp when the application was submitted.
    """

    class Meta:
        model = Applicant
        fields = '__all__'
