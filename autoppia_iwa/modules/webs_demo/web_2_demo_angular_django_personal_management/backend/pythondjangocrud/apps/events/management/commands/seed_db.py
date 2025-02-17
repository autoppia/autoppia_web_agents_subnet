from django.core.management.base import BaseCommand
from ...reset_seed import reset_database  

class Command(BaseCommand):
    help = "Seeds the database with initial data."

    def handle(self, *args, **options):
        reset_database()
        self.stdout.write(self.style.SUCCESS("Database seeded successfully."))
