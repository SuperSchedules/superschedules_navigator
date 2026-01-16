"""
Validate existing discovered URLs with LLM and update statuses.

Only processes POIs with:
- websites: website_status=FOUND (skips VALIDATED, REJECTED, etc.)
- events: source_status=DISCOVERED (skips VALIDATED, REJECTED, etc.)

With --cleanup flag:
- Valid URLs → status set to VALIDATED
- Invalid URLs → status set to REJECTED

Usage:
    python manage.py validate_urls websites --limit 100
    python manage.py validate_urls websites --category school --limit 50
    python manage.py validate_urls events --limit 100
    python manage.py validate_urls events --all --cleanup  # Validate ALL and update statuses
"""

import asyncio
from urllib.parse import urlparse

import requests
from django.core.management.base import BaseCommand
from django.db.models import Q
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from navigator.models import POI, BlockedDomain
from navigator.services.website_finder import validate_with_llm_text
from navigator.services.event_page_finder import validate_events_page_with_llm

console = Console()
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'


class Command(BaseCommand):
    help = 'Validate existing discovered URLs with LLM'

    def add_arguments(self, parser):
        parser.add_argument('mode', choices=['websites', 'events'], help='What to validate')
        parser.add_argument('--limit', type=int, default=50, help='Number of POIs to check')
        parser.add_argument('--category', type=str, help='Filter by category')
        parser.add_argument('--cleanup', action='store_true', help='Reset invalid POIs for re-discovery')
        parser.add_argument('--auto-block', action='store_true', help='Auto-add garbage domains to blocklist')
        parser.add_argument('--all', action='store_true', help='Validate ALL matching POIs (ignores --limit)')
        parser.add_argument('--reverse', action='store_true', help='Process POIs in reverse order (for parallel runs)')

    def handle(self, *args, **options):
        mode = options['mode']
        limit = options['limit']
        category = options['category']
        cleanup = options['cleanup']
        auto_block = options['auto_block']
        validate_all = options['all']
        reverse = options['reverse']

        if mode == 'websites':
            self.validate_websites(limit, category, cleanup, auto_block, validate_all, reverse)
        else:
            self.validate_events(limit, category, cleanup, auto_block, validate_all, reverse)

    def fetch_html(self, url: str) -> str | None:
        """Fetch HTML from URL."""
        try:
            resp = requests.get(url, timeout=15, headers={'User-Agent': USER_AGENT}, allow_redirects=True)
            if resp.status_code == 200 and 'text/html' in resp.headers.get('content-type', ''):
                return resp.text
        except Exception:
            pass
        return None

    def validate_websites(self, limit: int, category: str | None, cleanup: bool, auto_block: bool, validate_all: bool, reverse: bool = False):
        """Validate discovered websites."""
        console.print(f"\n[bold]Validating discovered websites[/bold]")

        # Only process FOUND status (not already VALIDATED or REJECTED)
        queryset = POI.objects.filter(
            website_status=POI.WebsiteStatus.FOUND
        ).exclude(discovered_website='')
        if category:
            queryset = queryset.filter(category=category)
            console.print(f"Filtering by category: {category}")

        order = '-id' if reverse else 'id'
        if validate_all:
            pois = list(queryset.order_by(order))
            console.print(f"Validating ALL {len(pois)} POIs...{' (reverse)' if reverse else ''}")
        else:
            pois = list(queryset.order_by('?')[:limit])
            console.print(f"Validating {len(pois)} random POIs...")

        results = {'valid': [], 'invalid': [], 'error': []}
        domain_failures = {}  # Track failures by domain

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Validating...", total=len(pois))

            for poi in pois:
                url = poi.discovered_website
                domain = urlparse(url).netloc.lower()
                progress.update(task, description=f"[dim]{poi.category:12}[/dim] {poi.name[:30]}")

                html = self.fetch_html(url)
                if not html:
                    results['error'].append((poi, url, "Fetch failed"))
                    progress.advance(task)
                    continue

                result = asyncio.run(validate_with_llm_text(html, poi))

                if result.get('valid'):
                    results['valid'].append((poi, url, result.get('reason', '')))
                    # Update DB immediately if cleanup enabled
                    if cleanup:
                        rows = POI.objects.filter(id=poi.id).update(
                            website_status=POI.WebsiteStatus.VALIDATED,
                            website_discovery_notes='LLM validated'
                        )
                        console.print(f"  [green]✓[/green] {poi.name[:30]} [dim](saved)[/dim]")
                else:
                    results['invalid'].append((poi, url, result.get('reason', '')))
                    # Track domain failures
                    domain_failures[domain] = domain_failures.get(domain, 0) + 1
                    # Update DB immediately if cleanup enabled
                    if cleanup:
                        update_fields = {
                            'website_status': POI.WebsiteStatus.REJECTED,
                            'website_discovery_notes': f'LLM rejected: {result.get("reason", "")[:100]}',
                        }
                        # Also reject events_url if it's on the same domain
                        if poi.events_url:
                            events_domain = urlparse(poi.events_url).netloc.lower()
                            if events_domain == domain:
                                update_fields['source_status'] = POI.SourceStatus.REJECTED
                                update_fields['events_url_notes'] = 'Rejected: website domain was invalid'
                        POI.objects.filter(id=poi.id).update(**update_fields)
                        console.print(f"  [red]✗[/red] {poi.name[:30]} [dim](saved)[/dim]")

                progress.advance(task)

        # Summary
        console.print(f"\n[bold]Summary:[/bold]")
        console.print(f"  Valid:   [green]{len(results['valid'])}[/green]")
        console.print(f"  Invalid: [red]{len(results['invalid'])}[/red]")
        console.print(f"  Errors:  [yellow]{len(results['error'])}[/yellow]")

        # Show invalid table
        if results['invalid']:
            console.print(f"\n[bold red]Invalid websites ({len(results['invalid'])}):[/bold red]")
            table = Table(show_header=True)
            table.add_column("Category")
            table.add_column("Name")
            table.add_column("Domain")
            table.add_column("Reason")

            for poi, url, reason in results['invalid'][:30]:  # Show first 30
                domain = urlparse(url).netloc
                table.add_row(
                    poi.category,
                    poi.name[:25],
                    domain[:30],
                    reason[:40]
                )
            console.print(table)

            if len(results['invalid']) > 30:
                console.print(f"  ... and {len(results['invalid']) - 30} more")

        # Show most common failing domains
        if domain_failures:
            console.print(f"\n[bold]Most common failing domains:[/bold]")
            sorted_domains = sorted(domain_failures.items(), key=lambda x: x[1], reverse=True)[:15]
            for domain, count in sorted_domains:
                blocked = BlockedDomain.objects.filter(domain=domain).exists()
                status = "[dim](blocked)[/dim]" if blocked else ""
                console.print(f"  {count:3} | {domain} {status}")

        # Auto-block domains with multiple failures
        if auto_block:
            console.print(f"\n[bold]Auto-blocking domains with 3+ failures:[/bold]")
            for domain, count in domain_failures.items():
                if count >= 3:
                    # Don't block .gov, .edu, .org automatically
                    if any(domain.endswith(tld) for tld in ['.gov', '.edu', '.org', '.us']):
                        console.print(f"  Skipping trusted TLD: {domain}")
                        continue
                    obj, created = BlockedDomain.objects.get_or_create(
                        domain=domain,
                        defaults={'reason': f'Auto-blocked: {count} validation failures'}
                    )
                    if created:
                        console.print(f"  [red]Blocked:[/red] {domain} ({count} failures)")

        # Summary of DB updates (already done inline)
        if cleanup:
            console.print(f"\n[green]Updated {len(results['valid'])} POIs as VALIDATED[/green]")
            console.print(f"[yellow]Updated {len(results['invalid'])} POIs as REJECTED[/yellow]")

    def validate_events(self, limit: int, category: str | None, cleanup: bool, auto_block: bool, validate_all: bool, reverse: bool = False):
        """Validate discovered events URLs."""
        console.print(f"\n[bold]Validating discovered events URLs[/bold]")

        # Only process DISCOVERED status (not already VALIDATED or REJECTED)
        queryset = POI.objects.filter(
            source_status=POI.SourceStatus.DISCOVERED
        ).exclude(events_url='')

        if category:
            queryset = queryset.filter(category=category)
            console.print(f"Filtering by category: {category}")

        order = '-id' if reverse else 'id'
        if validate_all:
            pois = list(queryset.order_by(order))
            console.print(f"Validating ALL {len(pois)} POIs...{' (reverse)' if reverse else ''}")
        else:
            pois = list(queryset.order_by('?')[:limit])
            console.print(f"Validating {len(pois)} random POIs...")

        results = {'valid': [], 'invalid': [], 'error': []}
        domain_failures = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Validating...", total=len(pois))

            for poi in pois:
                url = poi.events_url
                domain = urlparse(url).netloc.lower()
                progress.update(task, description=f"[dim]{poi.category:12}[/dim] {poi.name[:30]}")

                html = self.fetch_html(url)
                if not html:
                    results['error'].append((poi, url, "Fetch failed"))
                    progress.advance(task)
                    continue

                result = asyncio.run(validate_events_page_with_llm(html, url, poi))

                if result.get('has_events'):
                    results['valid'].append((poi, url, result.get('reason', '')))
                    # Update DB immediately if cleanup enabled
                    if cleanup:
                        POI.objects.filter(id=poi.id).update(
                            source_status=POI.SourceStatus.VALIDATED,
                            events_url_notes='LLM validated'
                        )
                else:
                    results['invalid'].append((poi, url, result.get('reason', '')))
                    domain_failures[domain] = domain_failures.get(domain, 0) + 1
                    # Update DB immediately if cleanup enabled
                    if cleanup:
                        POI.objects.filter(id=poi.id).update(
                            source_status=POI.SourceStatus.REJECTED,
                            events_url_notes=f'LLM rejected: {result.get("reason", "")[:100]}'
                        )

                progress.advance(task)

        # Summary
        console.print(f"\n[bold]Summary:[/bold]")
        console.print(f"  Valid:   [green]{len(results['valid'])}[/green]")
        console.print(f"  Invalid: [red]{len(results['invalid'])}[/red]")
        console.print(f"  Errors:  [yellow]{len(results['error'])}[/yellow]")

        # Show invalid table
        if results['invalid']:
            console.print(f"\n[bold red]Invalid events URLs ({len(results['invalid'])}):[/bold red]")
            table = Table(show_header=True)
            table.add_column("Category")
            table.add_column("Name")
            table.add_column("Domain")
            table.add_column("Reason")

            for poi, url, reason in results['invalid'][:30]:
                domain = urlparse(url).netloc
                table.add_row(
                    poi.category,
                    poi.name[:25],
                    domain[:30],
                    reason[:40]
                )
            console.print(table)

        # Summary of DB updates (already done inline)
        if cleanup:
            console.print(f"\n[green]Updated {len(results['valid'])} POIs as VALIDATED[/green]")
            console.print(f"[yellow]Updated {len(results['invalid'])} POIs as REJECTED[/yellow]")
