"""Admin configuration for Navigator models."""

from django.contrib import admin
from django.utils.html import format_html
from .models import Target, TargetQuery, Discovery, Run


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
        if obj.has_events and obj.location_correct:
            return format_html('<span style="color: green;">✓</span>')
        elif obj.location_correct is False:
            return format_html('<span style="color: red;">✗</span>')
        elif obj.has_events is False:
            return format_html('<span style="color: gray;">○</span>')
        return format_html('<span style="color: orange;">?</span>')
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


# Customize admin site
admin.site.site_header = "Navigator Admin"
admin.site.site_title = "Navigator"
admin.site.index_title = "Event Source Discovery"
