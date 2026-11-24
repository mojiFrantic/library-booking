from django.core.management.base import BaseCommand

from reservations.services import expire_stale_pickups


class Command(BaseCommand):
    help = "Mark reservations whose pickup deadline passed as expired."

    def handle(self, *args, **options):
        count = expire_stale_pickups()
        self.stdout.write(self.style.SUCCESS(f"Expired {count} reservation(s)."))