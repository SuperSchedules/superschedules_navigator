"""Match university CSV to POIs and reset them for event discovery."""

import csv
from pathlib import Path

from django.core.management.base import BaseCommand
from rich.console import Console
from rich.table import Table

from navigator.models import POI

console = Console()

DEFAULT_CSV = Path(__file__).resolve().parent.parent.parent.parent / 'massachusetts_universities.csv'


class Command(BaseCommand):
    help = 'Match university CSV to POIs and reset them for event discovery'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv',
            type=str,
            default=str(DEFAULT_CSV),
            help=f'Path to university CSV (default: {DEFAULT_CSV})'
        )
        parser.add_argument(
            '--greater-boston',
            action='store_true',
            help='Only process universities in Greater Boston area'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )

    def handle(self, *args, **options):
        csv_path = Path(options['csv'])
        greater_boston_only = options['greater_boston']
        dry_run = options['dry_run']

        if not csv_path.exists():
            console.print(f"[red]Error:[/red] CSV file not found: {csv_path}")
            return

        # Load CSV
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            universities = list(reader)

        console.print(f"\n[bold]University Prioritization[/bold]")
        console.print(f"CSV: {csv_path}")
        console.print(f"Universities in CSV: {len(universities)}")

        if greater_boston_only:
            universities = [u for u in universities if u.get('greater_boston', '').lower() == 'yes']
            console.print(f"Filtered to Greater Boston: {len(universities)}")

        if dry_run:
            console.print("[yellow]DRY RUN - no changes will be made[/yellow]")

        console.print()

        # Match and process
        matched = []
        unmatched = []

        for uni in universities:
            name = uni['name']
            city = uni.get('city', '')

            # Try to find matching POI(s)
            # First try exact match
            pois = list(POI.objects.filter(category='university', name__iexact=name))

            # If no exact match, try contains
            if not pois:
                pois = list(POI.objects.filter(category='university', name__icontains=name))

            if pois:
                matched.append({
                    'csv_name': name,
                    'csv_city': city,
                    'pois': pois,
                    'classification': uni.get('classification', ''),
                })

                if not dry_run:
                    # Reset POIs for discovery
                    for poi in pois:
                        poi.source_status = POI.SourceStatus.NOT_STARTED
                        poi.events_url = ''
                        poi.events_url_method = ''
                        poi.events_url_confidence = None
                        poi.events_url_notes = ''
                        poi.save(update_fields=[
                            'source_status', 'events_url', 'events_url_method',
                            'events_url_confidence', 'events_url_notes'
                        ])
            else:
                unmatched.append({
                    'name': name,
                    'city': city,
                    'classification': uni.get('classification', ''),
                })

        # Print results
        self._print_results(matched, unmatched, dry_run)

    def _print_results(self, matched: list, unmatched: list, dry_run: bool):
        """Print matching results."""
        # Matched table
        table = Table(title="Matched Universities")
        table.add_column("University", style="cyan")
        table.add_column("POI Matches", justify="right")
        table.add_column("Classification")

        for m in matched:
            poi_names = ', '.join(p.name for p in m['pois'][:2])
            if len(m['pois']) > 2:
                poi_names += f" (+{len(m['pois']) - 2} more)"
            table.add_row(m['csv_name'], str(len(m['pois'])), m['classification'])

        console.print(table)

        # Unmatched table
        if unmatched:
            console.print()
            table = Table(title="Unmatched (no POI found)")
            table.add_column("University", style="yellow")
            table.add_column("City")
            table.add_column("Classification")

            for u in unmatched:
                table.add_row(u['name'], u['city'], u['classification'])

            console.print(table)

        # Summary
        console.print()
        total_pois = sum(len(m['pois']) for m in matched)
        if dry_run:
            console.print(f"[green]Would reset {total_pois} POIs for discovery[/green]")
        else:
            console.print(f"[green]Reset {total_pois} POIs for discovery[/green]")
        console.print(f"Matched: {len(matched)} universities")
        console.print(f"Unmatched: {len(unmatched)} universities")
