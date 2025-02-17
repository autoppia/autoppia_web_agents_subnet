import os
from datetime import datetime
from pathlib import Path

import django
from django.utils.timezone import make_aware
from pythondjangocrud.apps.events.models import Event

# Set up Django environment
base_dir = Path(__file__).resolve().parent
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jobs.settings')
django.setup()

from pythondjangocrud.apps.users.models import User


def reset_database():
    """Reset the database state and re-seed with initial data."""
    # Clear the jobs table
    Event.objects.all().delete()
    print("All jobs deleted successfully.")

    # Get or create an admin user
    user, created = User.objects.get_or_create(
        email="test@test.com",
        defaults={
           
            "is_staff": True,
            "is_superuser": True,
        },
    )
    if created:
        user.set_password("test123")  # Set a secure default password
        user.save()
        print("Admin user created.")
    else:
        print("Admin user already exists.")

   # TODO: ADD SEED