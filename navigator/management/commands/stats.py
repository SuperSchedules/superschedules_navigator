"""Show discovery statistics."""

from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from navigator.models import Target, Discovery


class Command(BaseCommand):
    help = 'Show discovery statistics'

    def add_arguments(self, parser):
        parser.add_argument(
            '--type',
            help='Filter by target type'
        )

    def handle(self, *args, **options):
        console = Console()
        target_type = options.get('type')

        # Filter queryset if type specified
        targets = Target.objects.all()
        discoveries = Discovery.objects.all()
        if target_type:
            targets = targets.filter(target_type=target_type)
            discoveries = discoveries.filter(target__target_type=target_type)

        # Target stats
        target_stats = targets.aggregate(
            total=Count('id'),
            pending=Count('id', filter=Q(status='pending')),
            processing=Count('id', filter=Q(status='processing')),
            completed=Count('id', filter=Q(status='completed')),
            failed=Count('id', filter=Q(status='failed')),
        )

        # Target type breakdown
        type_breakdown = targets.values('target_type').annotate(count=Count('id')).order_by('-count')

        # Discovery stats
        discovery_stats = discoveries.aggregate(
            total=Count('id'),
            event_sources=Count('id', filter=Q(has_events=True, location_correct=True)),
            wrong_location=Count('id', filter=Q(location_correct=False)),
            no_events=Count('id', filter=Q(has_events=False, location_correct=True)),
            unclassified=Count('id', filter=Q(has_events__isnull=True)),
            pushed=Count('id', filter=Q(pushed_to_api=True)),
        )

        # Org type breakdown
        org_breakdown = discoveries.filter(
            has_events=True, location_correct=True
        ).exclude(org_type='').values('org_type').annotate(count=Count('id')).order_by('-count')

        # Build output
        title = "Navigator Statistics"
        if target_type:
            title += f" ({target_type})"

        # Targets table
        targets_table = Table(title="Targets", show_header=False, box=None)
        targets_table.add_column("Metric", style="cyan")
        targets_table.add_column("Value", justify="right")
        targets_table.add_row("Total", str(target_stats['total']))
        targets_table.add_row("Pending", str(target_stats['pending']))
        targets_table.add_row("Completed", str(target_stats['completed']))
        targets_table.add_row("Failed", str(target_stats['failed']))

        # Type breakdown table
        if not target_type and type_breakdown:
            type_table = Table(title="By Type", show_header=False, box=None)
            type_table.add_column("Type", style="cyan")
            type_table.add_column("Count", justify="right")
            for row in type_breakdown:
                type_table.add_row(row['target_type'], str(row['count']))
        else:
            type_table = None

        # Discoveries table
        disc_table = Table(title="Discoveries", show_header=False, box=None)
        disc_table.add_column("Metric", style="cyan")
        disc_table.add_column("Value", justify="right")
        disc_table.add_row("Total URLs", str(discovery_stats['total']))
        disc_table.add_row("[green]Event sources[/green]", f"[green]{discovery_stats['event_sources']}[/green]")
        disc_table.add_row("[red]Wrong location[/red]", f"[red]{discovery_stats['wrong_location']}[/red]")
        disc_table.add_row("No events", str(discovery_stats['no_events']))
        disc_table.add_row("Unclassified", str(discovery_stats['unclassified']))
        disc_table.add_row("Pushed to API", str(discovery_stats['pushed']))

        # Calculate percentages
        if discovery_stats['total'] > 0:
            event_pct = discovery_stats['event_sources'] / discovery_stats['total'] * 100
            disc_table.add_row("", "")
            disc_table.add_row("Success rate", f"{event_pct:.1f}%")

        # Org breakdown table
        if org_breakdown:
            org_table = Table(title="Event Sources by Org Type", show_header=False, box=None)
            org_table.add_column("Type", style="cyan")
            org_table.add_column("Count", justify="right")
            for row in org_breakdown:
                org_table.add_row(row['org_type'], str(row['count']))
        else:
            org_table = None

        # Print output
        console.print()
        console.print(Panel(title, style="bold blue"))
        console.print()
        console.print(targets_table)
        console.print()
        if type_table:
            console.print(type_table)
            console.print()
        console.print(disc_table)
        console.print()
        if org_table:
            console.print(org_table)
            console.print()
