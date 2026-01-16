"""Show POI statistics."""

from django.core.management.base import BaseCommand
from django.db.models import Count
from rich.console import Console
from rich.table import Table

from navigator.models import POI

console = Console()


class Command(BaseCommand):
    help = 'Show POI statistics'

    def add_arguments(self, parser):
        parser.add_argument(
            '--category',
            type=str,
            help='Filter by category'
        )
        parser.add_argument(
            '--city',
            type=str,
            help='Filter by city'
        )

    def handle(self, *args, **options):
        pois = POI.objects.all()

        if options.get('category'):
            pois = pois.filter(category=options['category'])

        if options.get('city'):
            pois = pois.filter(city__icontains=options['city'])

        total = pois.count()

        if total == 0:
            console.print("[yellow]No POIs found[/yellow]")
            return

        console.print(f"\n[bold]POI Statistics[/bold]")
        console.print("=" * 50)

        # Total count
        console.print(f"\n[cyan]Total POIs:[/cyan] {total}")

        # By category
        category_counts = pois.values('category').annotate(count=Count('id')).order_by('-count')

        cat_table = Table(title="By Category")
        cat_table.add_column("Category", style="cyan")
        cat_table.add_column("Count", justify="right")
        cat_table.add_column("With Website", justify="right")

        for row in category_counts:
            category = row['category']
            count = row['count']
            with_website = pois.filter(category=category).exclude(osm_website='').count()
            pct = f"({with_website * 100 // count}%)" if count > 0 else ""
            cat_table.add_row(category, str(count), f"{with_website} {pct}")

        console.print(cat_table)

        # Venue sync status
        venue_table = Table(title="Venue Sync Status")
        venue_table.add_column("Status", style="cyan")
        venue_table.add_column("Count", justify="right")

        venue_counts = pois.values('venue_status').annotate(count=Count('id'))
        for row in venue_counts:
            status = row['venue_status']
            status_display = dict(POI.VenueStatus.choices).get(status, status)
            count = row['count']
            style = "green" if status == 'synced' else "yellow" if status == 'pending' else "red"
            venue_table.add_row(status_display, str(count), style=style)

        console.print(venue_table)

        # Source discovery status
        source_table = Table(title="Source Discovery Status")
        source_table.add_column("Status", style="cyan")
        source_table.add_column("Count", justify="right")

        source_counts = pois.values('source_status').annotate(count=Count('id'))
        for row in source_counts:
            status = row['source_status']
            status_display = dict(POI.SourceStatus.choices).get(status, status)
            count = row['count']
            style = "green" if status == 'discovered' else "dim" if status in ('not_started', 'skipped') else "yellow"
            source_table.add_row(status_display, str(count), style=style)

        console.print(source_table)

        # Top cities
        city_counts = pois.exclude(city='').values('city').annotate(count=Count('id')).order_by('-count')[:10]

        if city_counts:
            city_table = Table(title="Top Cities")
            city_table.add_column("City", style="cyan")
            city_table.add_column("Count", justify="right")

            for row in city_counts:
                city_table.add_row(row['city'], str(row['count']))

            console.print(city_table)

        # Website coverage
        with_website = pois.exclude(osm_website='').count()
        console.print(f"\n[cyan]Website coverage:[/cyan] {with_website}/{total} ({with_website * 100 // total}%)")

        # Event pages discovered
        discovered = pois.filter(source_status=POI.SourceStatus.DISCOVERED).count()
        console.print(f"[cyan]Event pages found:[/cyan] {discovered}")

        # Sources synced to backend
        sources_synced = pois.filter(source_id__isnull=False).count()
        console.print(f"[cyan]Sources synced:[/cyan] {sources_synced}")

        console.print()
