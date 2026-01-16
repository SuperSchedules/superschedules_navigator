"""Extract POIs from OpenStreetMap PBF files using streaming (low memory)."""

import logging
from pathlib import Path
from typing import Iterator

import osmium
import reverse_geocoder as rg

logger = logging.getLogger(__name__)

# OSM tag to category mapping
TAG_CATEGORIES = {
    ('amenity', 'library'): 'library',
    ('tourism', 'museum'): 'museum',
    ('amenity', 'community_centre'): 'community_centre',
    ('amenity', 'theatre'): 'theatre',
    ('amenity', 'arts_centre'): 'arts_centre',
    ('amenity', 'school'): 'school',
    ('amenity', 'university'): 'university',
    ('amenity', 'college'): 'university',
    ('leisure', 'park'): 'park',
    ('leisure', 'playground'): 'playground',
    ('leisure', 'sports_centre'): 'sports_centre',
    ('amenity', 'townhall'): 'townhall',
}


class POIHandler(osmium.SimpleHandler):
    """Osmium handler that extracts POIs matching our categories."""

    def __init__(self, categories: list[str] | None = None):
        super().__init__()
        self.categories = categories
        self.pois = []
        self.stats = {
            'nodes_processed': 0,
            'ways_processed': 0,
            'relations_processed': 0,
            'skipped_no_category': 0,
            'skipped_no_name': 0,
            'skipped_wrong_category': 0,
        }

    def _get_category(self, tags) -> str | None:
        """Determine category from OSM tags."""
        for (tag_key, tag_value), category in TAG_CATEGORIES.items():
            if tags.get(tag_key) == tag_value:
                return category
        return None

    def _extract_poi(self, osm_type: str, osm_id: int, tags, lat: float | None, lon: float | None):
        """Extract POI data from an OSM element."""
        category = self._get_category(tags)
        if not category:
            self.stats['skipped_no_category'] += 1
            return

        if self.categories and category not in self.categories:
            self.stats['skipped_wrong_category'] += 1
            return

        name = tags.get('name')
        if not name:
            self.stats['skipped_no_name'] += 1
            return

        # Build address
        address_parts = []
        if tags.get('addr:housenumber'):
            address_parts.append(tags.get('addr:housenumber'))
        if tags.get('addr:street'):
            address_parts.append(tags.get('addr:street'))

        # Clean website URL
        website = tags.get('website', '') or tags.get('contact:website', '') or ''
        if website and not website.startswith(('http://', 'https://')):
            website = f"https://{website}"

        self.pois.append({
            'osm_type': osm_type,
            'osm_id': osm_id,
            'name': name,
            'category': category,
            'latitude': lat,
            'longitude': lon,
            'street_address': ' '.join(address_parts),
            'city': tags.get('addr:city', '') or '',
            'postal_code': tags.get('addr:postcode', '') or '',
            'osm_website': website,
            'osm_phone': tags.get('phone', '') or tags.get('contact:phone', '') or '',
            'osm_opening_hours': tags.get('opening_hours', '') or '',
            'osm_operator': tags.get('operator', '') or '',
            'osm_wikidata': tags.get('wikidata', '') or '',
        })

    def node(self, n):
        """Process a node (point feature)."""
        self.stats['nodes_processed'] += 1
        tags = {tag.k: tag.v for tag in n.tags}

        # Quick filter - only process if it might be a POI
        if not any(tags.get(k) for k in ('amenity', 'tourism', 'leisure')):
            return

        self._extract_poi('node', n.id, tags, n.location.lat, n.location.lon)

    def way(self, w):
        """Process a way (polygon/line feature)."""
        self.stats['ways_processed'] += 1
        tags = {tag.k: tag.v for tag in w.tags}

        # Quick filter
        if not any(tags.get(k) for k in ('amenity', 'tourism', 'leisure')):
            return

        # For ways, we need to calculate centroid from nodes
        # osmium provides a centroid helper when using LocationsOnWays
        if w.nodes:
            try:
                # Calculate centroid from way nodes
                lats = []
                lons = []
                for node in w.nodes:
                    if node.location.valid():
                        lats.append(node.location.lat)
                        lons.append(node.location.lon)

                if lats and lons:
                    lat = sum(lats) / len(lats)
                    lon = sum(lons) / len(lons)
                    self._extract_poi('way', w.id, tags, lat, lon)
            except Exception:
                # Some ways don't have location data
                pass

    def relation(self, r):
        """Process a relation (multi-polygon feature)."""
        self.stats['relations_processed'] += 1
        tags = {tag.k: tag.v for tag in r.tags}

        # Quick filter
        if not any(tags.get(k) for k in ('amenity', 'tourism', 'leisure')):
            return

        # Relations are complex - skip coordinate extraction for now
        # Most POIs are nodes or ways anyway
        self._extract_poi('relation', r.id, tags, None, None)


def _backfill_cities_from_coords(pois: list[dict]) -> int:
    """
    Backfill missing city data using reverse geocoding from lat/lon.

    Args:
        pois: List of POI dicts to potentially update in-place.

    Returns:
        Number of POIs that had city backfilled.
    """
    # Find POIs missing city but having valid coordinates
    pois_needing_city = [
        (i, poi) for i, poi in enumerate(pois)
        if not poi.get('city') and poi.get('latitude') is not None and poi.get('longitude') is not None
    ]

    if not pois_needing_city:
        return 0

    logger.info(f"Backfilling city for {len(pois_needing_city)} POIs using reverse geocoding...")

    # Prepare coordinates for batch lookup
    coords = [(poi['latitude'], poi['longitude']) for _, poi in pois_needing_city]

    try:
        results = rg.search(coords)
        backfilled = 0
        for (idx, poi), result in zip(pois_needing_city, results):
            city_name = result.get('name', '')
            if city_name:
                pois[idx]['city'] = city_name
                backfilled += 1
        logger.info(f"  Successfully backfilled {backfilled} cities")
        return backfilled
    except Exception as e:
        logger.warning(f"  Reverse geocoding failed: {e}")
        return 0


def extract_pois(pbf_path: Path, categories: list[str] | None = None) -> Iterator[dict]:
    """
    Extract POIs from OSM PBF file using streaming (low memory).

    Args:
        pbf_path: Path to the .osm.pbf file
        categories: Optional list of categories to filter (e.g., ['library', 'museum'])

    Yields:
        Dicts with venue data ready for POI model creation.
    """
    logger.info(f"Loading PBF file: {pbf_path}")

    handler = POIHandler(categories=categories)

    # Use LocationsOnWays to get node coordinates for ways
    handler.apply_file(str(pbf_path), locations=True)

    logger.info(f"Streaming complete:")
    logger.info(f"  Nodes processed: {handler.stats['nodes_processed']}")
    logger.info(f"  Ways processed: {handler.stats['ways_processed']}")
    logger.info(f"  Relations processed: {handler.stats['relations_processed']}")
    logger.info(f"  POIs extracted: {len(handler.pois)}")
    logger.info(f"  Skipped (no matching category): {handler.stats['skipped_no_category']}")
    logger.info(f"  Skipped (wrong category filter): {handler.stats['skipped_wrong_category']}")
    logger.info(f"  Skipped (no name): {handler.stats['skipped_no_name']}")

    # Backfill missing city data using reverse geocoding
    _backfill_cities_from_coords(handler.pois)

    yield from handler.pois
