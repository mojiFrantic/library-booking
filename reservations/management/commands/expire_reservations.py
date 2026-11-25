from django.core.management.base import BaseCommand

from reservations.services import run_maintenance


class Command(BaseCommand):
    help = (
        "Expire timed-out pickups and waitlist claims, then offer free "
        "copies to people in the waitlist."
    )

    def handle(self, *args, **options):
        pickups, claims, promoted = run_maintenance()
        self.stdout.write(
            self.style.SUCCESS(
                f"Expired {pickups} pickup(s) and {claims} waitlist claim(s); "
                f"notified {promoted} waiting reader(s)."
            )
        )