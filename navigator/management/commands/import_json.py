"""Import existing discovery_*.json files into the database."""

import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.utils import timezone
from navigator.models import Target, Discovery


class Command(BaseCommand):
    help = 'Import discovery JSON files into the database'

    def add_arguments(self, parser):
        parser.add_argument(
            'files',
            nargs='*',
            help='JSON files to import (default: all discovery_*.json in current directory)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without actually importing'
        )

    def handle(self, *args, **options):
        files = options['files']
        dry_run = options['dry_run']

        # Find files to import
        if not files:
            files = list(Path('.').glob('discovery_*.json'))
            if not files:
                self.stderr.write(self.style.ERROR('No discovery_*.json files found'))
                return
        else:
            files = [Path(f) for f in files]

        self.stdout.write(f"Found {len(files)} files to import")
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - no changes will be made'))

        total_targets = 0
        total_discoveries = 0
        total_skipped = 0

        for filepath in sorted(files):
            self.stdout.write(f"\nProcessing {filepath}...")

            try:
                with open(filepath) as f:
                    data = json.load(f)
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  Error reading {filepath}: {e}"))
                continue

            if not isinstance(data, list):
                self.stderr.write(self.style.ERROR(f"  Expected list, got {type(data).__name__}"))
                continue

            # Group by town to create targets
            file_targets = {}
            for record in data:
                town = record.get('town', '')
                state = record.get('state', 'MA')
                if not town:
                    continue

                key = (town, state)
                if key not in file_targets:
                    file_targets[key] = []
                file_targets[key].append(record)

            for (town, state), records in file_targets.items():
                # Create or get target
                if not dry_run:
                    target, created = Target.objects.get_or_create(
                        name=town,
                        target_type='town',
                        location=state,
                        defaults={
                            'status': 'completed',
                            'source_file': str(filepath),
                            'processed_at': timezone.now(),
                        }
                    )
                    if created:
                        total_targets += 1
                else:
                    # Check if would be created
                    exists = Target.objects.filter(name=town, target_type='town', location=state).exists()
                    if not exists:
                        total_targets += 1
                    target = None

                # Import discoveries
                for record in records:
                    url = record.get('url', '')
                    if not url:
                        continue

                    # Check if already exists
                    if Discovery.objects.filter(url=url).exists():
                        total_skipped += 1
                        continue

                    classification = record.get('classification', {})

                    if not dry_run:
                        # Handle None values and bad types from JSON
                        location_found = classification.get('location_found')
                        org_type = classification.get('org_type')
                        confidence = classification.get('confidence')
                        reason = classification.get('reason')
                        event_count = classification.get('event_count')

                        # event_count should be int or None
                        if event_count is not None and not isinstance(event_count, int):
                            # Try to extract a number
                            if isinstance(event_count, str):
                                import re
                                match = re.search(r'\d+', str(event_count))
                                event_count = int(match.group()) if match else None
                            else:
                                event_count = None

                        Discovery.objects.create(
                            target=target,
                            url=url,
                            domain=record.get('domain', ''),
                            title=record.get('title', ''),
                            category=record.get('category', ''),
                            screenshot_path=record.get('screenshot', ''),
                            location_correct=classification.get('location_correct'),
                            location_found=location_found if location_found else '',
                            has_events=classification.get('has_events'),
                            event_count=event_count,
                            org_type=org_type if org_type else '',
                            confidence=confidence if confidence else '',
                            reason=reason if reason else '',
                            model_used='minicpm-v',  # Assumed from existing data
                            classified_at=timezone.now(),
                        )
                    total_discoveries += 1

            self.stdout.write(f"  Processed {len(file_targets)} targets, {len(data)} records")

        # Summary
        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Would create {total_targets} new targets"))
            self.stdout.write(self.style.SUCCESS(f"Would import {total_discoveries} discoveries"))
            self.stdout.write(f"Would skip {total_skipped} existing URLs")
        else:
            self.stdout.write(self.style.SUCCESS(f"Created {total_targets} new targets"))
            self.stdout.write(self.style.SUCCESS(f"Imported {total_discoveries} discoveries"))
            self.stdout.write(f"Skipped {total_skipped} existing URLs")
