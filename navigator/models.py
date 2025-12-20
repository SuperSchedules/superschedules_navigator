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
    """A discovered URL from searching for a target."""

    target = models.ForeignKey(Target, on_delete=models.CASCADE, related_name='discoveries')
    url = models.URLField(max_length=2000, unique=True)
    domain = models.CharField(max_length=255)
    title = models.CharField(max_length=500, blank=True)
    category = models.CharField(max_length=50, blank=True, help_text="Search category (library, parks, town, museum, community)")
    screenshot_path = models.CharField(max_length=500, blank=True)
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
