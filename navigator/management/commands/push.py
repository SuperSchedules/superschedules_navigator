"""Push verified event sources to the Superschedules API."""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from navigator.models import Discovery


class Command(BaseCommand):
    help = 'Push verified event sources to the Superschedules API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--type',
            choices=['town', 'university', 'museum', 'library', 'organization', 'venue'],
            help='Only push discoveries from this target type'
        )
        parser.add_argument(
            '--target',
            type=str,
            help='Only push discoveries from targets matching this name'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Max URLs to push (0 = all)'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=50,
            help='URLs per API request (default: 50)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be pushed without actually pushing'
        )
        parser.add_argument(
            '--include-pushed',
            action='store_true',
            help='Include already-pushed URLs (for re-pushing)'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Check API token
        if not dry_run and not settings.SUPERSCHEDULES_API_TOKEN:
            self.stdout.write(self.style.ERROR(
                "No API token configured. Set SUPERSCHEDULES_API_TOKEN env var."
            ))
            return

        # Build query for verified event sources
        discoveries = Discovery.objects.filter(
            has_events=True,
            location_correct=True,
        )

        if not options['include_pushed']:
            discoveries = discoveries.filter(pushed_to_api=False)

        if options['type']:
            discoveries = discoveries.filter(target__target_type=options['type'])

        if options['target']:
            discoveries = discoveries.filter(target__name__icontains=options['target'])

        discoveries = discoveries.select_related('target').order_by('target__name')

        if options['limit']:
            discoveries = discoveries[:options['limit']]

        discoveries = list(discoveries)

        if not discoveries:
            self.stdout.write(self.style.WARNING('No event sources to push'))
            return

        # Filter out URLs that are too long for the API (max 200 chars)
        MAX_URL_LENGTH = 200
        long_urls = [d for d in discoveries if len(d.url) > MAX_URL_LENGTH]
        if long_urls:
            self.stdout.write(self.style.WARNING(
                f"\nSkipping {len(long_urls)} URLs over {MAX_URL_LENGTH} chars:"
            ))
            for d in long_urls:
                self.stdout.write(f"  - {d.url[:60]}... ({len(d.url)} chars)")
            discoveries = [d for d in discoveries if len(d.url) <= MAX_URL_LENGTH]

        if not discoveries:
            self.stdout.write(self.style.WARNING('No valid URLs to push after filtering'))
            return

        # Show what we're pushing
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"EVENT SOURCES TO PUSH: {len(discoveries)}")
        self.stdout.write('='*60)

        by_target = {}
        for d in discoveries:
            target_name = f"{d.target.name} ({d.target.target_type})"
            if target_name not in by_target:
                by_target[target_name] = []
            by_target[target_name].append(d)

        for target_name, target_discoveries in by_target.items():
            self.stdout.write(f"\n{target_name}:")
            for d in target_discoveries:
                status = "✓" if d.pushed_to_api else "○"
                self.stdout.write(f"  {status} {d.url[:70]}...")

        if dry_run:
            self.stdout.write(self.style.WARNING(f"\nDRY RUN - would push {len(discoveries)} URLs"))
            return

        # Push to API in batches
        batch_size = options['batch_size']
        total_pushed = 0
        total_failed = 0

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"PUSHING {len(discoveries)} URLs TO API")
        self.stdout.write(f"Batch size: {batch_size}")
        self.stdout.write('='*60)
        self.stdout.write(f"API: {settings.SUPERSCHEDULES_API_URL}")

        # Process in batches
        for i in range(0, len(discoveries), batch_size):
            batch = discoveries[i:i + batch_size]
            urls = [d.url for d in batch]
            batch_num = (i // batch_size) + 1
            total_batches = (len(discoveries) + batch_size - 1) // batch_size

            self.stdout.write(f"\nBatch {batch_num}/{total_batches} ({len(urls)} URLs)...")
            if len(urls) <= 3:
                for url in urls:
                    self.stdout.write(f"  → {url[:70]}")

            try:
                response = requests.post(
                    f"{settings.SUPERSCHEDULES_API_URL}/api/v1/queue/bulk-submit-service",
                    json={"urls": urls},
                    headers={"Authorization": f"Bearer {settings.SUPERSCHEDULES_API_TOKEN}"},
                    timeout=60
                )

                if response.status_code == 200:
                    result = response.json()
                    submitted = result.get('submitted', len(urls))
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Submitted: {submitted}"))

                    # Mark as pushed
                    now = timezone.now()
                    for d in batch:
                        d.pushed_to_api = True
                        d.pushed_at = now
                        d.save()

                    total_pushed += len(batch)

                else:
                    self.stdout.write(self.style.ERROR(f"  ✗ API Error: {response.status_code}"))
                    self.stdout.write(f"    Response: {response.text[:200]}")
                    total_failed += len(batch)

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Failed: {e}"))
                total_failed += len(batch)

        # Summary
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"COMPLETE: {total_pushed} pushed, {total_failed} failed")
        self.stdout.write('='*60)
