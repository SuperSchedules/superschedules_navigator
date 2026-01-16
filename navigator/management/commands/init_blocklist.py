"""Initialize the blocked domains list with known garbage domains."""

from django.core.management.base import BaseCommand
from navigator.models import BlockedDomain

# Domains to block during web search discovery
BLOCKED_DOMAINS = [
    # Event aggregators (not the actual venue)
    ('eventbrite.com', 'Event aggregator'),
    ('eventbrite.co.uk', 'Event aggregator'),
    ('happeningnext.com', 'Event aggregator'),
    ('allevents.in', 'Event aggregator'),
    ('evvnt.com', 'Event aggregator'),
    ('10times.com', 'Event aggregator'),
    ('eventful.com', 'Event aggregator'),
    ('bandsintown.com', 'Event aggregator'),
    ('songkick.com', 'Event aggregator'),
    ('seatgeek.com', 'Ticket aggregator'),
    ('stubhub.com', 'Ticket aggregator'),
    ('ticketmaster.com', 'Ticket aggregator'),
    ('axs.com', 'Ticket aggregator'),
    ('vividseat.com', 'Ticket aggregator'),

    # Review/listing sites
    ('yelp.com', 'Review site'),
    ('tripadvisor.com', 'Review site'),
    ('tripadvisor.co.uk', 'Review site'),
    ('foursquare.com', 'Review site'),
    ('zomato.com', 'Review site'),

    # Maps/directions
    ('mapquest.com', 'Maps site'),
    ('maps.google.com', 'Maps site'),
    ('waze.com', 'Maps site'),

    # Real estate
    ('zillow.com', 'Real estate'),
    ('trulia.com', 'Real estate'),
    ('realtor.com', 'Real estate'),
    ('redfin.com', 'Real estate'),
    ('apartments.com', 'Real estate'),
    ('bostonapartments.com', 'Real estate'),

    # Travel/tourism aggregators
    ('thecrazytourist.com', 'Travel blog'),
    ('tripsavvy.com', 'Travel blog'),
    ('timeout.com', 'City guide'),
    ('thrillist.com', 'City guide'),
    ('infatuation.com', 'City guide'),

    # Social media
    ('facebook.com', 'Social media'),
    ('instagram.com', 'Social media'),
    ('twitter.com', 'Social media'),
    ('x.com', 'Social media'),
    ('linkedin.com', 'Social media'),
    ('nextdoor.com', 'Social media'),

    # Generic directories
    ('yellowpages.com', 'Business directory'),
    ('whitepages.com', 'Business directory'),
    ('chamberofcommerce.com', 'Business directory'),
    ('manta.com', 'Business directory'),
    ('bbb.org', 'Business directory'),

    # News aggregators (not event sources)
    ('patch.com', 'News aggregator'),
    ('hometownweekly.net', 'News aggregator'),

    # Wikipedia (info, not events)
    ('wikipedia.org', 'Encyclopedia'),
    ('en.wikipedia.org', 'Encyclopedia'),

    # Generic/spam
    ('meetup.com', 'Meetup platform'),
    ('groupon.com', 'Deals site'),
    ('living social.com', 'Deals site'),
]


class Command(BaseCommand):
    help = 'Initialize the blocked domains list'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing blocklist before adding'
        )

    def handle(self, *args, **options):
        if options['clear']:
            deleted, _ = BlockedDomain.objects.all().delete()
            self.stdout.write(f"Cleared {deleted} existing blocked domains")

        created = 0
        skipped = 0

        for domain, reason in BLOCKED_DOMAINS:
            obj, was_created = BlockedDomain.objects.get_or_create(
                domain=domain,
                defaults={'reason': reason}
            )
            if was_created:
                created += 1
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f"Blocklist initialized: {created} added, {skipped} already existed"
        ))
        self.stdout.write(f"Total blocked domains: {BlockedDomain.objects.count()}")
