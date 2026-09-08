from django.core.management import BaseCommand

from c3ds.core.models import Display


class Command(BaseCommand):
    help = "Reload all displays"

    def handle(self, *args, **options):
        # Through the model rather than one broadcast to the channel group: this stamps every
        # display with the reload, so one that was itself reloading - and therefore in no group
        # to receive it - finds out from the version it echoes on its next ping.
        displays = Display.objects.all()
        count = displays.count()
        # Always spread: this is the one command that reaches the whole fleet at once.
        displays.reload(delayed=True)
        self.stdout.write(self.style.SUCCESS(f'Reloading {count} display(s), spread out.'))
