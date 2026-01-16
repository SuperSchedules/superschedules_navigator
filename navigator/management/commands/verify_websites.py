"""Verify discovered websites using vision LLM."""

import asyncio

from django.core.management.base import BaseCommand
from django.db.models import Q
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from navigator.models import POI
from navigator.services.website_verifier import verify_poi_website

console = Console()


class Command(BaseCommand):
    help = 'Verify discovered websites using vision LLM'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            help='Maximum number of POIs to verify'
        )
        parser.add_argument(
            '--category',
            type=str,
            help='Only verify POIs of this category'
        )
        parser.add_argument(
            '--city',
            type=str,
            help='Only verify POIs in this city'
        )
        parser.add_argument(
            '--reverify',
            action='store_true',
            help='Re-verify already verified POIs'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be verified without making changes'
        )

    def handle(self, *args, **options):
        limit = options.get('limit')
        category = options.get('category')
        city = options.get('city')
        reverify = options.get('reverify', False)
        dry_run = options.get('dry_run', False)

        # Query POIs with discovered websites
        queryset = POI.objects.exclude(discovered_website='')

        # Exclude already verified unless --reverify
        if not reverify:
            queryset = queryset.exclude(
                Q(website_discovery_notes__contains='VERIFIED:') |
                Q(website_discovery_notes__contains='REJECTED:')
            )

        if category:
            queryset = queryset.filter(category=category)

        if city:
            queryset = queryset.filter(city__icontains=city)

        queryset = queryset.order_by('city', 'category', 'name')

        if limit:
            queryset = queryset[:limit]

        pois = list(queryset)
        total = len(pois)

        if total == 0:
            console.print("[green]No POIs to verify![/green]")
            return

        console.print(f"\n[bold]Verifying {total} POI websites[/bold]")
        if dry_run:
            console.print("[yellow]DRY RUN - no changes will be made[/yellow]")

        # Stats
        stats = {
            'verified': 0,
            'rejected': 0,
            'uncertain': 0,
            'screenshot_failed': 0,
            'errors': 0,
        }

        # Rejected sites for review
        rejected = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Verifying...", total=total)

            for poi in pois:
                progress.update(task, description=f"Verifying: {poi.name[:30]}")

                if dry_run:
                    console.print(f"  Would verify: {poi.name} - {poi.discovered_website}")
                    progress.advance(task)
                    continue

                try:
                    result = asyncio.run(verify_poi_website(poi))

                    if result.get('screenshot_failed'):
                        stats['screenshot_failed'] += 1
                        notes = f"SCREENSHOT_FAILED: {result.get('reason', 'Unknown')}"
                        status_icon = "[dim]SCREENSHOT FAILED[/dim]"
                    elif result.get('is_correct') is True:
                        stats['verified'] += 1
                        conf = result.get('confidence', 'unknown')
                        detected = result.get('detected_name', '')
                        notes = f"VERIFIED: [{conf}] {detected} - {result.get('reason', '')}"
                        status_icon = "[green]VERIFIED[/green]"
                    elif result.get('is_correct') is False:
                        stats['rejected'] += 1
                        detected = result.get('detected_name', '')
                        reason = result.get('reason', '')
                        notes = f"REJECTED: {detected} - {reason}"
                        status_icon = "[red]REJECTED[/red]"
                        rejected.append({
                            'poi': poi,
                            'detected': detected,
                            'reason': reason,
                        })
                    else:
                        stats['uncertain'] += 1
                        notes = f"UNCERTAIN: {result.get('reason', 'No clear answer')}"
                        status_icon = "[yellow]UNCERTAIN[/yellow]"

                    # Show result for each POI
                    console.print(f"\n{status_icon} {poi.name} ({poi.category}) - {poi.city}")
                    console.print(f"  [dim]URL:[/dim] {poi.discovered_website}")
                    if result.get('detected_name'):
                        console.print(f"  [dim]Detected:[/dim] {result.get('detected_name')}")
                    if result.get('reason'):
                        console.print(f"  [dim]Reason:[/dim] {result.get('reason')}")
                    if result.get('raw_response') and result.get('is_correct') is None:
                        # Show full response for uncertain cases
                        console.print(f"  [dim]Raw response:[/dim]")
                        for line in result.get('raw_response', '').split('\n'):
                            console.print(f"    {line}")

                    # Update POI
                    poi.website_discovery_notes = notes[:500]
                    poi.save(update_fields=['website_discovery_notes'])

                except Exception as e:
                    stats['errors'] += 1
                    console.print(f"[red]Error verifying {poi.name}: {e}[/red]")

                progress.advance(task)

        # Summary
        console.print(f"\n[bold]Verification Summary[/bold]")
        console.print("=" * 50)
        console.print(f"[green]Verified:[/green] {stats['verified']}")
        console.print(f"[red]Rejected:[/red] {stats['rejected']}")
        console.print(f"[yellow]Uncertain:[/yellow] {stats['uncertain']}")
        console.print(f"[dim]Screenshot failed:[/dim] {stats['screenshot_failed']}")
        console.print(f"[red]Errors:[/red] {stats['errors']}")

        # Show rejected sites
        if rejected:
            console.print(f"\n[bold red]Rejected Sites ({len(rejected)})[/bold red]")
            table = Table()
            table.add_column("POI", style="cyan")
            table.add_column("City")
            table.add_column("URL", style="dim")
            table.add_column("Actually Is", style="yellow")
            table.add_column("Reason")

            for r in rejected[:20]:  # Show first 20
                poi = r['poi']
                table.add_row(
                    poi.name[:25],
                    poi.city[:15],
                    poi.discovered_website[:40],
                    r['detected'][:25],
                    r['reason'][:40],
                )

            console.print(table)

            if len(rejected) > 20:
                console.print(f"[dim]... and {len(rejected) - 20} more[/dim]")
