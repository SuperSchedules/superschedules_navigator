"""Import targets from CSV files."""

import csv
from pathlib import Path
from django.core.management.base import BaseCommand
from navigator.models import Target


class Command(BaseCommand):
    help = 'Import targets from CSV file'

    def add_arguments(self, parser):
        parser.add_argument('file', help='CSV file to import')
        parser.add_argument(
            '--type',
            default='town',
            choices=['town', 'university', 'museum', 'library', 'organization', 'venue'],
            help='Target type (default: town)'
        )
        parser.add_argument(
            '--location',
            default='MA',
            help='Default location/state (default: MA)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without actually importing'
        )

    def handle(self, *args, **options):
        filepath = Path(options['file'])
        target_type = options['type']
        default_location = options['location']
        dry_run = options['dry_run']

        if not filepath.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {filepath}"))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - no changes will be made'))

        created = 0
        skipped = 0

        with open(filepath, newline='', encoding='utf-8') as f:
            # Try to detect if there's a header
            sample = f.read(1024)
            f.seek(0)
            try:
                has_header = csv.Sniffer().has_header(sample)
            except csv.Error:
                # Single-column CSV, assume first row is header
                has_header = True

            reader = csv.reader(f)

            if has_header:
                headers = [h.lower().strip() for h in next(reader)]
                self.stdout.write(f"Detected headers: {headers}")

                # Determine column indices
                name_idx = None
                type_idx = None
                location_idx = None

                for i, h in enumerate(headers):
                    if h in ('name', 'town', 'city', 'target'):
                        name_idx = i
                    elif h in ('type', 'target_type'):
                        type_idx = i
                    elif h in ('location', 'state', 'region'):
                        location_idx = i

                if name_idx is None:
                    # Assume first column is name
                    name_idx = 0
            else:
                # No header, assume single column of names
                name_idx = 0
                type_idx = None
                location_idx = None

            for row in reader:
                if not row or not row[0].strip():
                    continue

                name = row[name_idx].strip()

                # Get type from CSV or use default
                if type_idx is not None and len(row) > type_idx and row[type_idx].strip():
                    row_type = row[type_idx].strip().lower()
                else:
                    row_type = target_type

                # Get location from CSV or use default
                if location_idx is not None and len(row) > location_idx and row[location_idx].strip():
                    location = row[location_idx].strip()
                else:
                    location = default_location

                # Check if exists
                exists = Target.objects.filter(
                    name=name,
                    target_type=row_type,
                    location=location
                ).exists()

                if exists:
                    skipped += 1
                    continue

                if not dry_run:
                    Target.objects.create(
                        name=name,
                        target_type=row_type,
                        location=location,
                        status='pending',
                        source_file=str(filepath),
                    )
                created += 1

        # Summary
        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Would create {created} new targets"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Created {created} new targets"))
        self.stdout.write(f"Skipped {skipped} existing targets")
