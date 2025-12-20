"""Run vision-based discovery on pending targets."""

import asyncio
import base64
import json
import re
import time
from pathlib import Path

import requests
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from django.utils import timezone

from navigator.models import Target, Discovery


# Configuration
OLLAMA_URL = "http://localhost:11434"
SCREENSHOT_DIR = Path("screenshots")


class Command(BaseCommand):
    help = 'Run discovery on pending targets'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Max targets to process (0 = all)'
        )
        parser.add_argument(
            '--target',
            type=str,
            help='Process specific target by name'
        )
        parser.add_argument(
            '--type',
            choices=['town', 'university', 'museum', 'library', 'organization', 'venue'],
            help='Only process targets of this type'
        )
        parser.add_argument(
            '--model',
            default='minicpm-v',
            help='Vision model to use (default: minicpm-v)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without running'
        )
        parser.add_argument(
            '--push',
            action='store_true',
            help='Push discovered event sources to API'
        )

    def handle(self, *args, **options):
        self.model = options['model']
        self.dry_run = options['dry_run']
        self.push = options['push']

        # Check Ollama
        if not self.dry_run:
            if not self.check_ollama():
                return

        # Build query
        targets = Target.objects.filter(status='pending')

        if options['target']:
            targets = targets.filter(name__icontains=options['target'])

        if options['type']:
            targets = targets.filter(target_type=options['type'])

        targets = targets.order_by('id')

        if options['limit']:
            targets = targets[:options['limit']]

        targets = list(targets)

        if not targets:
            self.stdout.write(self.style.WARNING('No pending targets found'))
            return

        self.stdout.write(f"\nFound {len(targets)} pending targets")

        if self.dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN - would process:'))
            for t in targets[:20]:
                self.stdout.write(f"  - {t.name} ({t.target_type}) - {t.location}")
            if len(targets) > 20:
                self.stdout.write(f"  ... and {len(targets) - 20} more")
            return

        # Process each target
        SCREENSHOT_DIR.mkdir(exist_ok=True)

        for i, target in enumerate(targets, 1):
            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(f"[{i}/{len(targets)}] {target.name} ({target.target_type})")
            self.stdout.write('='*60)

            target.status = 'processing'
            target.save()

            try:
                asyncio.run(self.discover_target(target))
                target.status = 'completed'
                target.processed_at = timezone.now()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error: {e}"))
                target.status = 'failed'

            target.save()

            # Delay between targets
            if i < len(targets):
                self.stdout.write("Waiting 3 seconds...")
                time.sleep(3)

        # Summary
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write("COMPLETE")
        self.stdout.write('='*60)

    def check_ollama(self) -> bool:
        """Check Ollama is running with vision model"""
        try:
            response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
            if response.status_code != 200:
                self.stdout.write(self.style.ERROR("Ollama not responding"))
                return False

            models = response.json().get("models", [])
            model_names = [m.get("name", "").split(":")[0] for m in models]

            if self.model not in model_names:
                self.stdout.write(self.style.ERROR(
                    f"Model '{self.model}' not found. Available: {model_names}"
                ))
                self.stdout.write(f"Run: ollama pull {self.model}")
                return False

            self.stdout.write(self.style.SUCCESS(f"Ollama OK, using {self.model}"))
            return True

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Ollama not available: {e}"))
            self.stdout.write("Start with: ollama serve")
            return False

    async def discover_target(self, target: Target):
        """Run discovery for a single target"""
        from ddgs import DDGS

        # Build search queries based on target type
        queries = self.get_search_queries(target)

        # Config per target type
        if target.target_type == 'museum':
            max_results = 3
            stop_on_high_confidence = True
        elif target.target_type == 'library':
            max_results = 3
            stop_on_high_confidence = True
        else:
            max_results = 5
            stop_on_high_confidence = False

        seen_domains = set()
        # Wrap DB query in sync_to_async
        existing_urls = await sync_to_async(
            lambda: set(Discovery.objects.filter(target=target).values_list('url', flat=True))
        )()
        seen_urls = existing_urls
        found_high_confidence = False

        for category, query in queries:
            if found_high_confidence:
                self.stdout.write(f"\n--- Skipping {category} (already found high-confidence match) ---")
                continue

            self.stdout.write(f"\n--- {category}: {query[:50]}... ---")

            try:
                results = list(DDGS().text(query, max_results=max_results))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Search error: {e}"))
                continue

            for result in results:
                url = result.get('href', '')
                title = result.get('title', '')
                domain = url.split('/')[2] if len(url.split('/')) > 2 else ''

                if url in seen_urls:
                    self.stdout.write(f"  Skip (already checked): {domain}")
                    continue

                if domain in seen_domains:
                    self.stdout.write(f"  Skip (duplicate domain): {domain}")
                    continue

                seen_domains.add(domain)
                seen_urls.add(url)

                self.stdout.write(f"\n  Checking: {title[:40]}...")
                self.stdout.write(f"  URL: {url[:60]}...")

                # Screenshot
                safe_name = f"{target.name}_{category}_{len(seen_urls)}.png".replace(' ', '_')
                screenshot_path = SCREENSHOT_DIR / safe_name

                self.stdout.write("  Taking screenshot...")
                success = await self.screenshot_url(url, screenshot_path)

                if not success:
                    # Save as unclassified
                    await sync_to_async(Discovery.objects.create)(
                        target=target,
                        url=url,
                        domain=domain,
                        title=title,
                        category=category,
                    )
                    continue

                # Classify
                self.stdout.write(f"  Classifying with {self.model}...")
                classification = self.classify_screenshot(screenshot_path, target)

                self.stdout.write(f"  Result: {classification}")

                # Save to database
                await sync_to_async(Discovery.objects.create)(
                    target=target,
                    url=url,
                    domain=domain,
                    title=title,
                    category=category,
                    location_correct=classification.get('location_correct'),
                    location_found=(classification.get('location_found') or '')[:255],
                    has_events=classification.get('has_events'),
                    event_count=self.parse_event_count(classification.get('event_count')),
                    org_type=(classification.get('org_type') or '')[:255],
                    confidence=classification.get('confidence') or '',
                    reason=classification.get('reason') or '',
                    model_used=self.model,
                    screenshot_path=str(screenshot_path),
                )

                # Check for early exit on high-confidence match
                if (stop_on_high_confidence and
                    classification.get('has_events') and
                    classification.get('location_correct', True) and
                    classification.get('confidence') == 'high'):
                    self.stdout.write(self.style.SUCCESS(
                        f"  ✓ Found high-confidence event source, stopping search for {target.name}"
                    ))
                    found_high_confidence = True
                    break

                time.sleep(0.5)

    def get_search_queries(self, target: Target) -> list[tuple[str, str]]:
        """Generate search queries based on target type"""
        name = target.name
        location = target.location or "Massachusetts"

        if target.target_type == 'town':
            return [
                ('library', f'{name} public library events {location}'),
                ('parks', f'{name} parks recreation events calendar {location}'),
                ('town', f'{name} town hall events calendar {location}'),
                ('museum', f'{name} museum events {location}'),
                ('community', f'{name} community events calendar {location}'),
            ]

        elif target.target_type == 'university':
            return [
                ('calendar', f'{name} events calendar'),
                ('student', f'{name} student activities events'),
                ('arts', f'{name} arts concerts performances'),
                ('athletics', f'{name} athletics sports schedule'),
                ('lectures', f'{name} lectures speakers events'),
            ]

        elif target.target_type == 'museum':
            return [
                ('events', f'{name} events calendar'),
                ('exhibitions', f'{name} exhibitions programs'),
                ('tours', f'{name} tours workshops'),
                ('family', f'{name} family programs kids'),
            ]

        elif target.target_type == 'library':
            return [
                ('events', f'{name} events programs'),
                ('calendar', f'{name} event calendar'),
                ('kids', f'{name} children programs storytime'),
                ('adult', f'{name} adult programs workshops'),
            ]

        else:
            return [
                ('events', f'{name} events calendar {location}'),
                ('programs', f'{name} programs schedule {location}'),
            ]

    async def screenshot_url(self, url: str, output_path: Path) -> bool:
        """Take screenshot with Playwright"""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={'width': 1280, 'height': 800})

                try:
                    await page.goto(url, timeout=15000, wait_until='domcontentloaded')
                    await asyncio.sleep(2)
                    await page.screenshot(path=str(output_path), full_page=False)
                    await browser.close()
                    return True
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Screenshot failed: {e}"))
                    await browser.close()
                    return False

        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Playwright error: {e}"))
            return False

    def classify_screenshot(self, image_path: Path, target: Target) -> dict:
        """Send screenshot to vision model for classification"""
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')

        location = target.location or "Massachusetts"

        prompt = f"""Analyze this webpage screenshot.

TARGET: {target.name} ({target.target_type})
LOCATION: {location}

TASK 1 - LOCATION CHECK:
Is this page about {target.name} in {location}? Look for city/state in headers, footers, addresses.
- If wrong location (different state/city), mark location_correct: false

TASK 2 - EVENT CHECK:
Does this page show EVENTS people can attend? Events have:
- Specific dates (like "Dec 14" or "Jan 5, 2025")
- Titles/descriptions (like "Story Time", "Concert")
- Something you GO TO (not news, not meeting minutes)

JSON response:
{{"location_correct": true/false, "location_found": "city/state seen", "has_events": true/false, "event_count": number, "org_type": "library/museum/parks/town_government/university/event_aggregator/null", "confidence": "high/medium/low", "reason": "brief explanation"}}"""

        try:
            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "images": [image_data],
                    "stream": False,
                    "options": {"temperature": 0.1}
                },
                timeout=60
            )

            if response.status_code == 200:
                result_text = response.json().get("response", "")
                try:
                    json_match = re.search(r'\{[^}]+\}', result_text, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group())
                except:
                    pass
                return {"raw_response": result_text, "parse_error": True}
            else:
                return {"error": f"Ollama returned {response.status_code}"}

        except Exception as e:
            return {"error": str(e)}

    def parse_event_count(self, value) -> int | None:
        """Parse event count from potentially messy LLM output"""
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            match = re.search(r'\d+', value)
            return int(match.group()) if match else None
        return None
