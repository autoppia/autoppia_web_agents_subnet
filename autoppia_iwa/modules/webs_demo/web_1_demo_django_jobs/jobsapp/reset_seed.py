import os
from datetime import datetime
from pathlib import Path

import django
from django.utils.timezone import make_aware

from events.models import Event

# Set up Django environment
base_dir = Path(__file__).resolve().parent
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jobs.settings')
django.setup()

from jobsapp.models import Job
from accounts.models import User


def reset_database():
    """Reset the database state and re-seed with initial data."""
    # Clear the jobs table
    Job.objects.all().delete()
    Event.objects.all().delete()
    print("All jobs deleted successfully.")

    # Get or create an admin user
    user, created = User.objects.get_or_create(
        email="admin@jobsapp.com",
        defaults={
            "role": "admin",
            "gender": "male",
            "is_staff": True,
            "is_superuser": True,
        },
    )
    if created:
        user.set_password("admin123")  # Set a secure default password
        user.save()
        print("Admin user created.")
    else:
        print("Admin user already exists.")

    # Seed job data
    job_data = [
        ("Software Engineer", "Develop scalable applications.", "Remote", "Full-time", "Engineering", "Tech Innovators",
         "Innovative tech company", "https://www.techinnovators.com"),
        ("Data Scientist", "Analyze and interpret complex data.", "On-site", "Full-time", "Data Science", "DataTech",
         "Leading data-driven solutions.", "https://www.datatech.com"),
        ("Product Manager", "Oversee product lifecycle.", "Hybrid", "Full-time", "Product", "Productive Inc.",
         "Creating the best products.", "https://www.productiveinc.com"),
        ("UX Designer", "Design intuitive user interfaces.", "Remote", "Full-time", "Design", "Creative Minds",
         "Designing seamless user experiences.", "https://www.creativeminds.com"),
        ("Software Tester", "Ensure product quality through testing.", "On-site", "Contract", "QA", "Testify",
         "Your trusted QA partner.", "https://www.testify.com"),
        ("Business Analyst", "Analyze business needs and strategies.", "Remote", "Full-time", "Business", "BusinessGen",
         "Optimizing business strategies.", "https://www.businessgen.com"),
        ("Web Developer", "Develop dynamic web applications.", "Remote", "Full-time", "Engineering", "WebWorks",
         "Building the web, one site at a time.", "https://www.webworks.com"),
        ("Graphic Designer", "Create visual concepts and designs.", "On-site", "Full-time", "Design", "DesignPro",
         "Innovative visual designs.", "https://www.designpro.com"),
        ("System Administrator", "Maintain and support IT systems.", "On-site", "Full-time", "IT", "TechGuard",
         "Keeping systems running smoothly.", "https://www.techguard.com"),
        ("Network Engineer", "Design and implement network infrastructure.", "Hybrid", "Full-time", "Engineering",
         "NetWorks", "Connecting the world through networks.", "https://www.networks.com"),
        (
            "Marketing Manager", "Plan and execute marketing strategies.", "Remote", "Full-time", "Marketing",
            "MarketLeap",
            "Leading successful campaigns.", "https://www.marketleap.com"),
        ("Content Writer", "Create engaging content for blogs and websites.", "Remote", "Freelance", "Content",
         "WriteAway", "Crafting words that captivate.", "https://www.writeaway.com"),
        ("HR Specialist", "Manage human resources functions.", "On-site", "Full-time", "Human Resources", "PeopleCare",
         "Supporting your workforce.", "https://www.peoplecare.com"),
        ("Sales Executive", "Drive sales and client relationships.", "Hybrid", "Full-time", "Sales", "SalesForce",
         "Empowering sales professionals.", "https://www.salesforce.com"),
        ("SEO Specialist", "Optimize websites for search engines.", "Remote", "Contract", "Marketing", "SEOGenius",
         "Enhancing online visibility.", "https://www.seogenius.com")
    ]

    # Add jobs to the database
    for i, (title, description, location, job_type, category, company_name, company_description, website) in enumerate(
        job_data, 1):
        job = Job.objects.create(
            user=user,
            title=title,
            description=description,
            location=location,
            type=job_type,
            category=category,
            company_name=company_name,
            company_description=company_description,
            website=website,
            last_date=make_aware(datetime(2025, 12, 31, 0, 0, 0)),  # Use timezone-aware datetime
        )
        print(f"Job '{job.title}' added successfully!")
