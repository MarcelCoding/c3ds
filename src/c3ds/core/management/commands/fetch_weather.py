from django.core.management import BaseCommand

from c3ds.core.models import WeatherLocation


class Command(BaseCommand):
    help = 'Fetch the latest forecast for the configured locations from Bright Sky'

    def add_arguments(self, parser):
        parser.add_argument(
            '--id',
            type=int,
            help='Fetch the forecast for a specific WeatherLocation entry ID',
        )

    def handle(self, *args, **options):
        if options['id']:
            queryset = WeatherLocation.objects.filter(pk=options['id'])
        else:
            queryset = WeatherLocation.objects.all()

        if not queryset.exists():
            self.stdout.write(self.style.SUCCESS('No WeatherLocation entries need fetching'))
            return

        self.stdout.write(f'Fetching forecasts for {queryset.count()} entries...')
        for location in queryset:
            try:
                location.fetch_forecast()
                self.stdout.write(self.style.SUCCESS(f'  ✓ Updated "{location.name}"'))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f'  ✗ Failed "{location.name}": {e}'))

        self.stdout.write(self.style.SUCCESS('Done!'))
