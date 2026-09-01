from django.core.management import BaseCommand
from django.utils import timezone

from c3ds.core.models import MastodonPost


class Command(BaseCommand):
    help = 'Fetch latest posts from Mastodon instances via fedi.buzz API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Fetch posts for all MastodonPost entries',
        )
        parser.add_argument(
            '--id',
            type=int,
            help='Fetch posts for specific MastodonPost entry ID',
        )

    def handle(self, *args, **options):
        if options['id']:
            queryset = MastodonPost.objects.filter(pk=options['id'])
        elif options['all']:
            queryset = MastodonPost.objects.all()
        else:
            queryset = MastodonPost.objects.filter(
                last_fetched__lt=timezone.now() - timezone.timedelta(hours=1)
            ) | MastodonPost.objects.filter(last_fetched__isnull=True)

        if not queryset.exists():
            self.stdout.write(self.style.SUCCESS('No MastodonPost entries need fetching'))
            return

        self.stdout.write(f'Fetching posts for {queryset.count()} entries...')
        for post in queryset:
            try:
                post.fetch_posts()
                self.stdout.write(self.style.SUCCESS(f'  ✓ Updated "{post.name}"'))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f'  ✗ Failed "{post.name}": {e}'))

        self.stdout.write(self.style.SUCCESS('Done!'))
