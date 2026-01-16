"""Admin configuration for Navigator models."""

from django.contrib import admin
from django.utils.html import format_html
from .models import Target, TargetQuery, Discovery, Run, POI, PipelineRun, WorkerStatus, BlockedDomain


class TargetQueryInline(admin.TabularInline):
    model = TargetQuery
    extra = 1


@admin.register(Target)
class TargetAdmin(admin.ModelAdmin):
    list_display = ['name', 'target_type', 'location', 'status', 'discovery_count', 'event_source_count', 'processed_at']
    list_filter = ['target_type', 'status', 'source_file']
    search_fields = ['name', 'location']
    ordering = ['name']
    inlines = [TargetQueryInline]

    actions = ['mark_pending', 'mark_completed']

    def discovery_count(self, obj):
        return obj.discoveries.count()
    discovery_count.short_description = 'URLs'

    def event_source_count(self, obj):
        count = obj.discoveries.filter(has_events=True, location_correct=True).count()
        if count > 0:
            return format_html('<span style="color: green; font-weight: bold;">{}</span>', count)
        return count
    event_source_count.short_description = 'Events'

    @admin.action(description="Mark selected as pending")
    def mark_pending(self, request, queryset):
        queryset.update(status='pending', processed_at=None)

    @admin.action(description="Mark selected as completed")
    def mark_completed(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='completed', processed_at=timezone.now())


@admin.register(Discovery)
class DiscoveryAdmin(admin.ModelAdmin):
    list_display = ['status_icon', 'domain', 'target', 'category', 'has_events', 'location_correct', 'event_count', 'org_type', 'confidence', 'pushed_to_api']
    list_filter = ['has_events', 'location_correct', 'org_type', 'confidence', 'pushed_to_api', 'target__target_type', 'category']
    search_fields = ['url', 'domain', 'title', 'target__name']
    ordering = ['-discovered_at']
    raw_id_fields = ['target']

    readonly_fields = ['discovered_at', 'classified_at', 'pushed_at']

    actions = ['mark_as_pushed']

    def status_icon(self, obj):
        from django.utils.safestring import mark_safe
        if obj.has_events and obj.location_correct:
            return mark_safe('<span style="color: green;">✓</span>')
        elif obj.location_correct is False:
            return mark_safe('<span style="color: red;">✗</span>')
        elif obj.has_events is False:
            return mark_safe('<span style="color: gray;">○</span>')
        return mark_safe('<span style="color: orange;">?</span>')
    status_icon.short_description = ''

    @admin.action(description="Mark selected as pushed to API")
    def mark_as_pushed(self, request, queryset):
        from django.utils import timezone
        queryset.update(pushed_to_api=True, pushed_at=timezone.now())


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ['started_at', 'ended_at', 'targets_processed', 'urls_checked', 'event_sources_found', 'errors']
    ordering = ['-started_at']
    readonly_fields = ['started_at']


@admin.register(POI)
class POIAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'category', 'city', 'venue_status', 'website_status', 'source_status',
        'website_icon', 'events_url_link', 'osm_link'
    ]
    list_filter = ['category', 'venue_status', 'website_status', 'source_status']
    search_fields = ['name', 'city', 'osm_website', 'discovered_website']
    readonly_fields = ['osm_link', 'extracted_at', 'updated_at', 'effective_website']
    ordering = ['name']
    change_list_template = 'admin/poi_changelist.html'

    def changelist_view(self, request, extra_context=None):
        from django.db.models import Count, Q
        # Get status counts
        stats = POI.objects.aggregate(
            total=Count('id'),
            # Website status
            osm_website=Count('id', filter=Q(osm_website__gt='')),
            website_found=Count('id', filter=Q(website_status='found')),
            website_validated=Count('id', filter=Q(website_status='validated')),
            website_rejected=Count('id', filter=Q(website_status='rejected')),
            website_not_found=Count('id', filter=Q(website_status='not_found')),
            # Source status
            source_discovered=Count('id', filter=Q(source_status='discovered')),
            source_validated=Count('id', filter=Q(source_status='validated')),
            source_rejected=Count('id', filter=Q(source_status='rejected')),
            source_no_events=Count('id', filter=Q(source_status='no_events')),
        )
        extra_context = extra_context or {}
        extra_context['poi_stats'] = stats
        return super().changelist_view(request, extra_context=extra_context)

    fieldsets = [
        ('Basic Info', {
            'fields': ['name', 'category', 'osm_type', 'osm_id', 'osm_link']
        }),
        ('Location', {
            'fields': ['street_address', 'city', 'state', 'postal_code', 'latitude', 'longitude']
        }),
        ('OSM Data', {
            'fields': ['osm_website', 'osm_phone', 'osm_opening_hours', 'osm_operator', 'osm_wikidata']
        }),
        ('Venue Sync', {
            'fields': ['venue_status', 'venue_id', 'venue_synced_at', 'venue_sync_error']
        }),
        ('Website Discovery', {
            'fields': ['website_status', 'discovered_website', 'website_discovery_notes', 'effective_website']
        }),
        ('Events URL Discovery', {
            'fields': [
                'source_status', 'events_url', 'events_url_method',
                'events_url_confidence', 'events_url_notes'
            ]
        }),
        ('Legacy/History', {
            'fields': ['discovery', 'discovered_events_url', 'discovery_method', 'discovery_confidence',
                       'discovery_notes', 'source_id', 'source_synced_at'],
            'classes': ['collapse']
        }),
        ('Timestamps', {
            'fields': ['extracted_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]

    def website_icon(self, obj):
        from django.utils.safestring import mark_safe
        if obj.osm_website:
            return mark_safe('<span style="color: green;" title="From OSM">✓ OSM</span>')
        elif obj.website_status == 'validated':
            return mark_safe('<span style="color: green;" title="LLM Validated">✓</span>')
        elif obj.website_status == 'rejected':
            return mark_safe('<span style="color: red;" title="LLM Rejected">✗</span>')
        elif obj.website_status == 'found':
            return mark_safe('<span style="color: blue;" title="Found - needs validation">?</span>')
        elif obj.website_status == 'not_found':
            return mark_safe('<span style="color: orange;" title="Not found">-</span>')
        return mark_safe('<span style="color: #ccc;" title="Not started">○</span>')
    website_icon.short_description = 'Web'

    def effective_website(self, obj):
        website = obj.website
        if website:
            source = 'OSM' if obj.osm_website else 'Discovered'
            return format_html('<a href="{}" target="_blank">{}</a> ({})', website, website[:60], source)
        return '-'
    effective_website.short_description = 'Effective Website'

    def osm_link(self, obj):
        if obj.osm_type and obj.osm_id:
            return format_html('<a href="{}" target="_blank">View on OSM</a>', obj.osm_url)
        return '-'
    osm_link.short_description = 'OSM'

    def events_url_link(self, obj):
        from django.utils.safestring import mark_safe
        if obj.events_url:
            domain = obj.events_url.split('/')[2] if '/' in obj.events_url else obj.events_url
            if obj.source_status == 'validated':
                icon = '<span style="color: green;">✓</span> '
            elif obj.source_status == 'rejected':
                icon = '<span style="color: red;">✗</span> '
            elif obj.source_status == 'discovered':
                icon = '<span style="color: blue;">?</span> '
            else:
                icon = ''
            return format_html('{}<a href="{}" target="_blank">{}</a>', mark_safe(icon), obj.events_url, domain[:25])
        return mark_safe('<span style="color: #999;">-</span>')
    events_url_link.short_description = 'Events'

    actions = [
        'sync_venues', 'discover_sources',
        'reset_venue_status', 'reset_website_status', 'reset_source_status',
        'mark_website_validated', 'mark_website_rejected',
        'mark_source_validated', 'mark_source_rejected',
    ]

    @admin.action(description='Sync selected venues to backend')
    def sync_venues(self, request, queryset):
        # Will be implemented with poi_sync command logic
        self.message_user(request, f"Use 'python manage.py poi_sync' to sync venues.")

    @admin.action(description='Discover event pages for selected')
    def discover_sources(self, request, queryset):
        # Will be implemented with poi_discover command logic
        self.message_user(request, f"Use 'python manage.py poi_discover' to discover event pages.")

    @admin.action(description='Reset venue status to pending')
    def reset_venue_status(self, request, queryset):
        queryset.update(venue_status='pending', venue_id=None, venue_synced_at=None, venue_sync_error='')
        self.message_user(request, f"Reset venue status for {queryset.count()} POIs.")

    @admin.action(description='Reset website status to not started')
    def reset_website_status(self, request, queryset):
        queryset.update(website_status='not_started', discovered_website='', website_discovery_notes='')
        self.message_user(request, f"Reset website status for {queryset.count()} POIs.")

    @admin.action(description='Reset source status to not started')
    def reset_source_status(self, request, queryset):
        queryset.update(
            source_status='not_started', events_url='', events_url_method='',
            events_url_confidence=None, events_url_notes=''
        )
        self.message_user(request, f"Reset source status for {queryset.count()} POIs.")

    @admin.action(description='Mark website as VALIDATED')
    def mark_website_validated(self, request, queryset):
        count = queryset.filter(website_status='found').update(
            website_status='validated', website_discovery_notes='Manually validated'
        )
        self.message_user(request, f"Marked {count} POIs website as validated.")

    @admin.action(description='Mark website as REJECTED')
    def mark_website_rejected(self, request, queryset):
        count = queryset.filter(website_status='found').update(
            website_status='rejected', website_discovery_notes='Manually rejected'
        )
        self.message_user(request, f"Marked {count} POIs website as rejected.")

    @admin.action(description='Mark events URL as VALIDATED')
    def mark_source_validated(self, request, queryset):
        count = queryset.filter(source_status='discovered').update(
            source_status='validated', events_url_notes='Manually validated'
        )
        self.message_user(request, f"Marked {count} POIs events URL as validated.")

    @admin.action(description='Mark events URL as REJECTED')
    def mark_source_rejected(self, request, queryset):
        count = queryset.filter(source_status='discovered').update(
            source_status='rejected', events_url_notes='Manually rejected'
        )
        self.message_user(request, f"Marked {count} POIs events URL as rejected.")


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ['step', 'status', 'progress_display', 'results_display', 'started_at', 'completed_at']
    list_filter = ['step', 'status']
    ordering = ['-started_at']
    readonly_fields = ['started_at', 'completed_at', 'log']

    fieldsets = [
        ('Run Info', {
            'fields': ['step', 'status', 'started_at', 'completed_at']
        }),
        ('Filters', {
            'fields': ['categories', 'city_filter', 'limit', 'dry_run']
        }),
        ('Progress', {
            'fields': ['total_items', 'processed_items', 'current_item']
        }),
        ('Results', {
            'fields': ['created', 'updated', 'unchanged', 'failed', 'skipped']
        }),
        ('Log', {
            'fields': ['log'],
            'classes': ['collapse']
        }),
    ]

    def progress_display(self, obj):
        return f"{obj.processed_items}/{obj.total_items} ({obj.progress_pct}%)"
    progress_display.short_description = 'Progress'

    def results_display(self, obj):
        parts = []
        if obj.created:
            parts.append(f"+{obj.created}")
        if obj.updated:
            parts.append(f"~{obj.updated}")
        if obj.failed:
            parts.append(f'<span style="color: orange;">!{obj.failed}</span>')
        if not parts:
            return '-'
        from django.utils.safestring import mark_safe
        return mark_safe(' '.join(parts))
    results_display.short_description = 'Results'


@admin.register(WorkerStatus)
class WorkerStatusAdmin(admin.ModelAdmin):
    list_display = ['worker_type', 'status_icon', 'hostname', 'pois_processed', 'discoveries_found', 'last_heartbeat']
    readonly_fields = [
        'worker_type', 'hostname', 'pid', 'is_running', 'last_heartbeat', 'started_at',
        'current_poi', 'current_poi_name', 'pois_processed', 'discoveries_found',
        'discoveries_reused', 'errors'
    ]

    def status_icon(self, obj):
        from django.utils.safestring import mark_safe
        if obj.is_alive:
            return mark_safe('<span style="color: green;">● Running</span>')
        elif obj.is_running:
            return mark_safe('<span style="color: orange;">● Stale</span>')
        return mark_safe('<span style="color: gray;">○ Stopped</span>')
    status_icon.short_description = 'Status'


@admin.register(BlockedDomain)
class BlockedDomainAdmin(admin.ModelAdmin):
    list_display = ['domain', 'reason', 'created_at']
    search_fields = ['domain', 'reason']
    ordering = ['domain']


# Customize admin site
admin.site.site_header = "Navigator Admin"
admin.site.site_title = "Navigator"
admin.site.index_title = "Event Source Discovery"
admin.site.site_url = "/"  # Link "View Site" to dashboard
