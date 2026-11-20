import random

from django.core.management.base import BaseCommand

from books.models import Author, Book, Genre


class Command(BaseCommand):
    help = "Create sample authors, genres and books for development."

    def handle(self, *args, **options):
        genres = [
            Genre.objects.get_or_create(name=name)[0]
            for name in ["Fiction", "Science", "History", "Fantasy", "Biography"]
        ]
        authors = [
            Author.objects.get_or_create(name=f"Author {i}")[0] for i in range(1, 9)
        ]

        created = 0
        for i in range(1, 31):
            book, was_created = Book.objects.get_or_create(
                title=f"Sample Book {i}",
                defaults={
                    "summary": f"This is the summary of sample book {i}.",
                    "publication_year": random.randint(1950, 2024),
                    "total_copies": random.randint(0, 5),
                },
            )
            if was_created:
                book.authors.set(random.sample(authors, k=random.randint(1, 2)))
                book.genres.set(random.sample(genres, k=random.randint(1, 2)))
                created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} sample books."))