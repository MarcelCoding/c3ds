from django.core.management import BaseCommand

from c3ds.core.models import MastodonPost


class Command(BaseCommand):
    help = 'Fetch latest posts from Mastodon instances via fedi.buzz API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--id',
            type=int,
            help='Fetch posts for specific MastodonPost entry ID',
        )

    def handle(self, *args, **options):
        if options['id']:
            queryset = MastodonPost.objects.filter(pk=options['id'])
        else:
            queryset = MastodonPost.objects.all()

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
