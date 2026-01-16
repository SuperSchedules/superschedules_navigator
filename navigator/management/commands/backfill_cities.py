"""Backfill missing city data for POIs using reverse geocoding."""

from django.core.management.base import BaseCommand
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from navigator.models import POI

console = Console()


class Command(BaseCommand):
    help = 'Backfill missing city data for POIs using lat/lon reverse geocoding'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Number of POIs to process per batch (default: 1000)'
        )
        parser.add_argument(
            '--category',
            type=str,
            help='Only backfill POIs of this category'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Maximum number of POIs to process'
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        batch_size = options.get('batch_size', 1000)
        category = options.get('category')
        limit = options.get('limit')

        # Import reverse_geocoder (lazy import since it takes a moment to load data)
        console.print("[cyan]Loading reverse geocoder data...[/cyan]")
        import reverse_geocoder as rg

        # Query POIs with missing city but valid coordinates
        queryset = POI.objects.filter(city='').exclude(latitude__isnull=True).exclude(longitude__isnull=True)

        if category:
            queryset = queryset.filter(category=category)
            console.print(f"[dim]Filtering by category: {category}[/dim]")

        if limit:
            queryset = queryset[:limit]
            console.print(f"[dim]Limiting to {limit} POIs[/dim]")

        pois = list(queryset)
        total = len(pois)

        if total == 0:
            console.print("[green]No POIs with missing city data found![/green]")
            return

        console.print(f"\n[bold]Found {total} POIs with missing city data[/bold]")

        if dry_run:
            console.print("[yellow]DRY RUN - no changes will be made[/yellow]\n")

        # Process in batches
        updated_count = 0
        failed_count = 0
        city_counts = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Processing POIs...", total=total)

            for i in range(0, total, batch_size):
                batch = pois[i:i + batch_size]

                # Prepare coordinates for batch lookup
                coords = [(float(poi.latitude), float(poi.longitude)) for poi in batch]

                try:
                    # Batch reverse geocode
                    results = rg.search(coords)

                    # Update POIs with results
                    pois_to_update = []
                    for poi, result in zip(batch, results):
                        city_name = result.get('name', '')
                        if city_name:
                            poi.city = city_name
                            pois_to_update.append(poi)
                            city_counts[city_name] = city_counts.get(city_name, 0) + 1
                            updated_count += 1
                        else:
                            failed_count += 1

                    # Bulk update if not dry run
                    if not dry_run and pois_to_update:
                        POI.objects.bulk_update(pois_to_update, ['city'])

                except Exception as e:
                    console.print(f"[red]Error processing batch: {e}[/red]")
                    failed_count += len(batch)

                progress.update(task, advance=len(batch))

        # Summary
        console.print(f"\n[bold]Summary[/bold]")
        console.print("=" * 50)
        console.print(f"[cyan]Total processed:[/cyan] {total}")
        console.print(f"[green]Updated:[/green] {updated_count}")
        console.print(f"[red]Failed/No result:[/red] {failed_count}")

        if city_counts:
            console.print(f"\n[bold]Top cities found:[/bold]")
            sorted_cities = sorted(city_counts.items(), key=lambda x: -x[1])[:15]
            for city, count in sorted_cities:
                console.print(f"  {city}: {count}")

        if dry_run:
            console.print("\n[yellow]DRY RUN - run without --dry-run to apply changes[/yellow]")
        else:
            console.print(f"\n[green]Successfully updated {updated_count} POIs![/green]")
