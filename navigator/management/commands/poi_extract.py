"""Extract POIs from OpenStreetMap PBF file into the database."""

from pathlib import Path

from django.core.management.base import BaseCommand
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from navigator.models import POI
from navigator.services.osm_extractor import extract_pois

console = Console()


class Command(BaseCommand):
    help = 'Extract POIs from OpenStreetMap PBF file'

    def add_arguments(self, parser):
        parser.add_argument(
            '--pbf',
            type=str,
            required=True,
            help='Path to OSM PBF file (e.g., massachusetts-latest.osm.pbf)'
        )
        parser.add_argument(
            '--category',
            action='append',
            dest='categories',
            choices=[c[0] for c in POI.Category.choices],
            help='Only extract specific categories (can be repeated)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be extracted without saving'
        )
        parser.add_argument(
            '--download',
            action='store_true',
            help='Download PBF file first (requires --state)'
        )
        parser.add_argument(
            '--state',
            type=str,
            default='massachusetts',
            help='State to download from Geofabrik (default: massachusetts)'
        )

    def handle(self, *args, **options):
        pbf_path = Path(options['pbf'])
        categories = options.get('categories')
        dry_run = options['dry_run']

        if options['download']:
            pbf_path = self._download_pbf(options['state'])
            if not pbf_path:
                return

        if not pbf_path.exists():
            console.print(f"[red]Error:[/red] PBF file not found: {pbf_path}")
            console.print(f"\nDownload from: https://download.geofabrik.de/north-america/us/{options['state']}-latest.osm.pbf")
            return

        console.print(f"\n[bold]POI Extraction[/bold]")
        console.print(f"PBF file: {pbf_path}")
        if categories:
            console.print(f"Categories: {', '.join(categories)}")
        if dry_run:
            console.print("[yellow]DRY RUN - no changes will be saved[/yellow]")
        console.print()

        # Stats tracking
        stats = {
            'total': 0,
            'created': 0,
            'updated': 0,
            'unchanged': 0,
            'by_category': {},
        }

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Extracting POIs...", total=None)

            for poi_data in extract_pois(pbf_path, categories):
                stats['total'] += 1
                category = poi_data['category']
                stats['by_category'][category] = stats['by_category'].get(category, 0) + 1

                progress.update(task, description=f"Processing: {poi_data['name'][:40]}")

                if dry_run:
                    continue

                # Upsert POI by osm_type + osm_id
                result = self._upsert_poi(poi_data)
                stats[result] += 1

        # Print results
        self._print_results(stats, dry_run)

    def _upsert_poi(self, poi_data: dict) -> str:
        """
        Create or update POI record.

        Returns: 'created', 'updated', or 'unchanged'
        """
        osm_type = poi_data['osm_type']
        osm_id = poi_data['osm_id']

        try:
            existing = POI.objects.get(osm_type=osm_type, osm_id=osm_id)
            # Check if any fields changed
            changed = False
            for key, value in poi_data.items():
                if key in ('osm_type', 'osm_id'):
                    continue
                current_value = getattr(existing, key)
                # Handle decimal comparison
                if hasattr(current_value, '__float__') and value is not None:
                    if float(current_value) != float(value):
                        setattr(existing, key, value)
                        changed = True
                elif current_value != value:
                    setattr(existing, key, value)
                    changed = True

            if changed:
                existing.save()
                return 'updated'
            return 'unchanged'

        except POI.DoesNotExist:
            POI.objects.create(**poi_data)
            return 'created'

    def _download_pbf(self, state: str) -> Path | None:
        """Download PBF file from Geofabrik."""
        import requests

        url = f"https://download.geofabrik.de/north-america/us/{state}-latest.osm.pbf"
        output_path = Path(f"{state}-latest.osm.pbf")

        if output_path.exists():
            console.print(f"[yellow]PBF file already exists:[/yellow] {output_path}")
            return output_path

        console.print(f"Downloading {url}...")

        try:
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task("Downloading...", total=total_size)

                    with open(output_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))

            console.print(f"[green]Downloaded:[/green] {output_path}")
            return output_path

        except Exception as e:
            console.print(f"[red]Download failed:[/red] {e}")
            return None

    def _print_results(self, stats: dict, dry_run: bool):
        """Print extraction results."""
        console.print()

        # Summary table
        table = Table(title="Extraction Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right")

        table.add_row("Total extracted", str(stats['total']))
        if not dry_run:
            table.add_row("Created (new)", str(stats['created']), style="green")
            table.add_row("Updated", str(stats['updated']), style="yellow")
            table.add_row("Unchanged", str(stats['unchanged']), style="dim")

        console.print(table)

        # By category
        if stats['by_category']:
            cat_table = Table(title="By Category")
            cat_table.add_column("Category", style="cyan")
            cat_table.add_column("Count", justify="right")

            for category, count in sorted(stats['by_category'].items(), key=lambda x: -x[1]):
                cat_table.add_row(category, str(count))

            console.print(cat_table)
