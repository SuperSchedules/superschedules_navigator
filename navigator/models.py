"""Models for event source discovery."""

from django.db import models


class Target(models.Model):
    """A search target - could be a town, university, museum, etc."""

    class TargetType(models.TextChoices):
        TOWN = 'town', 'Town'
        UNIVERSITY = 'university', 'University'
        MUSEUM = 'museum', 'Museum'
        LIBRARY = 'library', 'Library'
        ORGANIZATION = 'organization', 'Organization'
        VENUE = 'venue', 'Venue'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    name = models.CharField(max_length=255, help_text="Name of the target (e.g., 'Newton', 'MIT', 'Museum of Fine Arts')")
    target_type = models.CharField(max_length=20, choices=TargetType.choices, default=TargetType.TOWN)
    location = models.CharField(max_length=255, blank=True, help_text="Location for disambiguation (e.g., 'MA', 'Boston, MA')")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    source_file = models.CharField(max_length=255, blank=True, help_text="CSV/file this target was imported from")
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['name', 'target_type', 'location']
        ordering = ['name']

    def __str__(self):
        if self.location:
            return f"{self.name} ({self.target_type}, {self.location})"
        return f"{self.name} ({self.target_type})"

    @property
    def discovery_count(self):
        return self.discoveries.count()

    @property
    def event_source_count(self):
        return self.discoveries.filter(has_events=True, location_correct=True).count()


class TargetQuery(models.Model):
    """Custom search query for a target (optional override of defaults)."""

    target = models.ForeignKey(Target, on_delete=models.CASCADE, related_name='custom_queries')
    query = models.CharField(max_length=500, help_text="Search query to use")
    category = models.CharField(max_length=50, blank=True, help_text="Category this query is for (e.g., 'library', 'events')")

    class Meta:
        verbose_name_plural = "Target queries"

    def __str__(self):
        return f"{self.target.name}: {self.query[:50]}"


class Discovery(models.Model):
    """A discovered URL - an event source that can serve multiple POIs."""

    # Legacy link to Target (for old discovery data)
    target = models.ForeignKey(Target, on_delete=models.CASCADE, related_name='discoveries', null=True, blank=True)

    url = models.URLField(max_length=2000, unique=True)
    domain = models.CharField(max_length=255)
    title = models.CharField(max_length=500, blank=True)
    category = models.CharField(max_length=50, blank=True, help_text="Search category (library, parks, town, museum, community)")
    screenshot_path = models.CharField(max_length=500, blank=True)

    # Location for grouping (e.g., all Needham parks share one discovery)
    city = models.CharField(max_length=100, blank=True, db_index=True)
    state = models.CharField(max_length=2, default='MA')
    discovered_at = models.DateTimeField(auto_now_add=True)

    # Classification results (denormalized for convenience)
    location_correct = models.BooleanField(null=True, help_text="Is this the correct location?")
    location_found = models.CharField(max_length=255, blank=True, help_text="Location detected on page")
    has_events = models.BooleanField(null=True, help_text="Does this page have events?")
    event_count = models.IntegerField(null=True, help_text="Approximate number of events visible")
    org_type = models.CharField(max_length=255, blank=True, help_text="Organization type detected")
    confidence = models.CharField(max_length=20, blank=True, help_text="Classification confidence (high/medium/low)")
    reason = models.TextField(blank=True, help_text="Explanation from vision model")
    model_used = models.CharField(max_length=50, blank=True, help_text="Vision model used for classification")
    classified_at = models.DateTimeField(null=True, blank=True)

    # API push tracking
    pushed_to_api = models.BooleanField(default=False)
    pushed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "Discoveries"
        ordering = ['-discovered_at']

    def __str__(self):
        status = "✓" if self.has_events and self.location_correct else "○"
        return f"{status} {self.domain}"

    @property
    def is_event_source(self):
        """Is this a verified event source (correct location + has events)?"""
        return self.has_events and self.location_correct


class Run(models.Model):
    """A discovery run session for tracking statistics."""

    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    targets_processed = models.IntegerField(default=0)
    urls_checked = models.IntegerField(default=0)
    event_sources_found = models.IntegerField(default=0)
    errors = models.IntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Run {self.started_at.strftime('%Y-%m-%d %H:%M')} - {self.targets_processed} targets"


class POI(models.Model):
    """
    Point of Interest extracted from OpenStreetMap.

    This is the navigator's local copy. Venues are synced to the main
    superschedules backend via API. Source discovery is a separate step.
    """

    class Category(models.TextChoices):
        LIBRARY = 'library', 'Library'
        MUSEUM = 'museum', 'Museum'
        COMMUNITY_CENTER = 'community_centre', 'Community Center'
        THEATRE = 'theatre', 'Theatre'
        ARTS_CENTER = 'arts_centre', 'Arts Center'
        SCHOOL = 'school', 'School'
        UNIVERSITY = 'university', 'University'
        PARK = 'park', 'Park'
        PLAYGROUND = 'playground', 'Playground'
        SPORTS_CENTER = 'sports_centre', 'Sports Center'
        TOWN_HALL = 'townhall', 'Town Hall'

    class VenueStatus(models.TextChoices):
        PENDING = 'pending', 'Pending Sync'
        SYNCED = 'synced', 'Synced to Backend'
        FAILED = 'failed', 'Sync Failed'

    class SourceStatus(models.TextChoices):
        NOT_STARTED = 'not_started', 'Not Started'
        PROCESSING = 'processing', 'Processing'
        DISCOVERED = 'discovered', 'Events Page Found'
        VALIDATED = 'validated', 'LLM Validated'
        REJECTED = 'rejected', 'LLM Rejected'
        NO_EVENTS = 'no_events', 'No Events Page Found'
        SKIPPED = 'skipped', 'Skipped (no website)'

    class WebsiteStatus(models.TextChoices):
        HAS_OSM = 'has_osm', 'Has OSM Website'
        NOT_STARTED = 'not_started', 'Not Started'
        PROCESSING = 'processing', 'Processing'
        FOUND = 'found', 'Website Found'
        VALIDATED = 'validated', 'LLM Validated'
        REJECTED = 'rejected', 'LLM Rejected'
        NOT_FOUND = 'not_found', 'No Website Found'
        FAILED = 'failed', 'Search Failed'

    # OSM identification
    osm_type = models.CharField(max_length=10)  # node, way, relation
    osm_id = models.BigIntegerField()

    # Basic info
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=50, choices=Category.choices)

    # Location
    street_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, default='MA')
    postal_code = models.CharField(max_length=20, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # From OSM tags
    osm_website = models.URLField(max_length=500, blank=True)
    osm_phone = models.CharField(max_length=50, blank=True)
    osm_opening_hours = models.TextField(blank=True)  # OSM format
    osm_operator = models.CharField(max_length=255, blank=True)
    osm_wikidata = models.CharField(max_length=50, blank=True)

    # Venue sync status (Step 1: sync venue to backend)
    venue_status = models.CharField(max_length=20, choices=VenueStatus.choices, default=VenueStatus.PENDING)
    venue_id = models.IntegerField(null=True, blank=True, help_text="ID in main superschedules system")
    venue_synced_at = models.DateTimeField(null=True, blank=True)
    venue_sync_error = models.TextField(blank=True)

    # Website discovery status (Step 2: find official website if no osm_website)
    website_status = models.CharField(max_length=20, choices=WebsiteStatus.choices, default=WebsiteStatus.NOT_STARTED)
    discovered_website = models.URLField(max_length=500, blank=True, help_text="Website found via web search")
    website_discovery_notes = models.TextField(blank=True)

    # Events URL discovery (Step 3: find events page, optional)
    source_status = models.CharField(max_length=20, choices=SourceStatus.choices, default=SourceStatus.NOT_STARTED)
    events_url = models.URLField(max_length=500, blank=True, help_text="URL where events are listed for this venue")
    events_url_method = models.CharField(max_length=50, blank=True, help_text="How events URL was found")
    events_url_confidence = models.FloatField(null=True, blank=True)
    events_url_notes = models.TextField(blank=True)

    # Link to Discovery for historical tracking (optional)
    discovery = models.ForeignKey(
        'Discovery',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='pois',
        help_text="Discovery record (for tracking/history)"
    )

    # Legacy fields (deprecated - use events_url instead)
    discovered_events_url = models.URLField(max_length=500, blank=True)
    discovery_method = models.CharField(max_length=50, blank=True)
    discovery_confidence = models.FloatField(null=True, blank=True)
    discovery_notes = models.TextField(blank=True)
    source_id = models.IntegerField(null=True, blank=True, help_text="Source ID in main superschedules system")
    source_synced_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    extracted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'POI'
        verbose_name_plural = 'POIs'
        unique_together = ['osm_type', 'osm_id']
        indexes = [
            models.Index(fields=['venue_status']),
            models.Index(fields=['website_status']),
            models.Index(fields=['source_status']),
            models.Index(fields=['category']),
            models.Index(fields=['city', 'state']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"

    @property
    def osm_url(self):
        """Link to view this POI on OpenStreetMap."""
        return f"https://www.openstreetmap.org/{self.osm_type}/{self.osm_id}"

    @property
    def has_website(self):
        return bool(self.osm_website or self.discovered_website)

    @property
    def website(self):
        """Get the best available website (OSM preferred, then discovered)."""
        return self.osm_website or self.discovered_website


class PipelineRun(models.Model):
    """Track pipeline step executions for history and monitoring."""

    class Step(models.TextChoices):
        EXTRACT = 'extract', 'POI Extraction'
        SYNC = 'sync', 'Venue Sync'
        DISCOVER = 'discover', 'Source Discovery'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    step = models.CharField(max_length=20, choices=Step.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    # Filters used
    categories = models.JSONField(default=list, blank=True)
    city_filter = models.CharField(max_length=100, blank=True)
    limit = models.IntegerField(default=0)
    dry_run = models.BooleanField(default=False)

    # Progress
    total_items = models.IntegerField(default=0)
    processed_items = models.IntegerField(default=0)
    current_item = models.CharField(max_length=255, blank=True)

    # Results
    created = models.IntegerField(default=0)
    updated = models.IntegerField(default=0)
    unchanged = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    skipped = models.IntegerField(default=0)

    # Timestamps
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Log output
    log = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'Pipeline Run'
        verbose_name_plural = 'Pipeline Runs'

    def __str__(self):
        status_icon = {'completed': '✓', 'failed': '✗', 'running': '⟳', 'pending': '○'}.get(self.status, '?')
        return f"{status_icon} {self.get_step_display()} - {self.started_at.strftime('%Y-%m-%d %H:%M') if self.started_at else 'Not started'}"

    @property
    def progress_pct(self):
        if self.total_items == 0:
            return 0
        return round(self.processed_items / self.total_items * 100)

    @property
    def is_running(self):
        return self.status == self.Status.RUNNING


class WorkerStatus(models.Model):
    """Track status of background worker processes."""

    class WorkerType(models.TextChoices):
        URL_DISCOVERY = 'url_discovery', 'URL Discovery Worker'

    worker_type = models.CharField(max_length=50, choices=WorkerType.choices, unique=True)
    hostname = models.CharField(max_length=255, blank=True)
    pid = models.IntegerField(null=True, blank=True)

    # Status
    is_running = models.BooleanField(default=False)
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)

    # Current work
    current_poi = models.ForeignKey(POI, null=True, blank=True, on_delete=models.SET_NULL)
    current_poi_name = models.CharField(max_length=255, blank=True)

    # Stats (since worker started)
    pois_processed = models.IntegerField(default=0)
    discoveries_found = models.IntegerField(default=0)
    discoveries_reused = models.IntegerField(default=0)
    errors = models.IntegerField(default=0)

    # Website discovery stats
    websites_found = models.IntegerField(default=0)
    websites_not_found = models.IntegerField(default=0)

    # Current phase
    current_phase = models.CharField(max_length=20, blank=True, help_text="'website' or 'events'")

    # Config
    batch_size = models.IntegerField(default=1)
    sleep_seconds = models.FloatField(default=2.0)

    class Meta:
        verbose_name = 'Worker Status'
        verbose_name_plural = 'Worker Statuses'

    def __str__(self):
        status = "Running" if self.is_running else "Stopped"
        return f"{self.get_worker_type_display()} - {status}"

    @property
    def is_alive(self):
        """Check if worker is alive (heartbeat within last 60 seconds)."""
        if not self.last_heartbeat:
            return False
        from django.utils import timezone
        from datetime import timedelta
        return (timezone.now() - self.last_heartbeat) < timedelta(seconds=60)

    @property
    def status_display(self):
        if not self.is_running:
            return "Stopped"
        if self.is_alive:
            return "Running"
        return "Stale (no heartbeat)"


class BlockedDomain(models.Model):
    """Domains to skip during web search discovery."""

    domain = models.CharField(max_length=255, unique=True, help_text="Domain to block (e.g., 'eventbrite.com')")
    reason = models.CharField(max_length=255, blank=True, help_text="Why this domain is blocked")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['domain']

    def __str__(self):
        return self.domain
