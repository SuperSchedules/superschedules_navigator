#!/usr/bin/env python
"""
Validate existing discovered websites/events URLs with LLM.

Usage:
    python validate_existing.py websites [--limit N] [--category CAT]
    python validate_existing.py events [--limit N] [--category CAT]

Examples:
    python validate_existing.py websites --limit 20
    python validate_existing.py websites --category school --limit 50
    python validate_existing.py events --limit 20
"""

import argparse
import asyncio
import sys
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

import requests
from rich.console import Console
from rich.table import Table

from navigator.models import POI
from navigator.services.website_finder import validate_with_llm_text
from navigator.services.event_page_finder import validate_events_page_with_llm

console = Console()

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'


def fetch_html(url: str) -> str | None:
    """Fetch HTML from URL."""
    try:
        resp = requests.get(url, timeout=15, headers={'User-Agent': USER_AGENT}, allow_redirects=True)
        if resp.status_code == 200 and 'text/html' in resp.headers.get('content-type', ''):
            return resp.text
    except Exception as e:
        console.print(f"[red]Fetch error: {e}[/red]")
    return None


async def validate_website(poi, html: str) -> dict:
    """Validate a website."""
    return await validate_with_llm_text(html, poi)


async def validate_events(poi, url: str, html: str) -> dict:
    """Validate an events page."""
    return await validate_events_page_with_llm(html, url, poi)


def run_website_validation(limit: int, category: str | None):
    """Validate discovered websites."""
    console.print(f"\n[bold]Validating discovered websites[/bold]")

    queryset = POI.objects.exclude(discovered_website='')
    if category:
        queryset = queryset.filter(category=category)

    pois = queryset.order_by('?')[:limit]
    console.print(f"Testing {len(pois)} POIs...\n")

    results = {'valid': [], 'invalid': [], 'error': []}

    for poi in pois:
        url = poi.discovered_website
        console.print(f"[dim]{poi.category:12}[/dim] {poi.name[:30]:30} ", end="")

        html = fetch_html(url)
        if not html:
            console.print("[yellow]FETCH ERROR[/yellow]")
            results['error'].append((poi, url, "Fetch failed"))
            continue

        result = asyncio.run(validate_website(poi, html))

        if result.get('valid'):
            console.print("[green]VALID[/green]")
            results['valid'].append((poi, url, result.get('reason', '')))
        else:
            console.print(f"[red]INVALID[/red] - {result.get('reason', '')[:50]}")
            results['invalid'].append((poi, url, result.get('reason', '')))

    # Summary
    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  Valid:   {len(results['valid'])}")
    console.print(f"  Invalid: {len(results['invalid'])}")
    console.print(f"  Errors:  {len(results['error'])}")

    if results['invalid']:
        console.print(f"\n[bold red]Invalid websites:[/bold red]")
        table = Table(show_header=True)
        table.add_column("Category")
        table.add_column("Name")
        table.add_column("URL")
        table.add_column("Reason")

        for poi, url, reason in results['invalid']:
            table.add_row(
                poi.category,
                poi.name[:25],
                url[:40] + "..." if len(url) > 40 else url,
                reason[:40]
            )
        console.print(table)


def run_events_validation(limit: int, category: str | None):
    """Validate discovered events URLs."""
    console.print(f"\n[bold]Validating discovered events URLs[/bold]")

    queryset = POI.objects.filter(
        source_status=POI.SourceStatus.DISCOVERED
    ).exclude(events_url='')

    if category:
        queryset = queryset.filter(category=category)

    pois = queryset.order_by('?')[:limit]
    console.print(f"Testing {len(pois)} POIs...\n")

    results = {'valid': [], 'invalid': [], 'error': []}

    for poi in pois:
        url = poi.events_url
        console.print(f"[dim]{poi.category:12}[/dim] {poi.name[:30]:30} ", end="")

        html = fetch_html(url)
        if not html:
            console.print("[yellow]FETCH ERROR[/yellow]")
            results['error'].append((poi, url, "Fetch failed"))
            continue

        result = asyncio.run(validate_events(poi, url, html))

        if result.get('has_events'):
            console.print("[green]VALID[/green]")
            results['valid'].append((poi, url, result.get('reason', '')))
        else:
            console.print(f"[red]INVALID[/red] - {result.get('reason', '')[:50]}")
            results['invalid'].append((poi, url, result.get('reason', '')))

    # Summary
    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  Valid:   {len(results['valid'])}")
    console.print(f"  Invalid: {len(results['invalid'])}")
    console.print(f"  Errors:  {len(results['error'])}")

    if results['invalid']:
        console.print(f"\n[bold red]Invalid events URLs:[/bold red]")
        table = Table(show_header=True)
        table.add_column("Category")
        table.add_column("Name")
        table.add_column("URL")
        table.add_column("Reason")

        for poi, url, reason in results['invalid']:
            table.add_row(
                poi.category,
                poi.name[:25],
                url[:40] + "..." if len(url) > 40 else url,
                reason[:40]
            )
        console.print(table)


def main():
    parser = argparse.ArgumentParser(description='Validate existing discovered URLs')
    parser.add_argument('mode', choices=['websites', 'events'], help='What to validate')
    parser.add_argument('--limit', type=int, default=20, help='Number of POIs to check')
    parser.add_argument('--category', type=str, help='Filter by category')

    args = parser.parse_args()

    if args.mode == 'websites':
        run_website_validation(args.limit, args.category)
    else:
        run_events_validation(args.limit, args.category)


if __name__ == '__main__':
    main()
