import requests
from django.core.management import BaseCommand
from django.db import transaction

from c3ds.core.models import DVBStop, DVBView, displays_showing

#: Community-maintained, regularly refreshed VVO stop directory.
STATIONS_URL = 'https://raw.githubusercontent.com/kiliankoe/vvo/main/data/stations.json'


class Command(BaseCommand):
    help = 'Import/update the VVO stop directory from github.com/kiliankoe/vvo, mirroring deletions too'

    def handle(self, *args, **options):
        resp = requests.get(STATIONS_URL, timeout=30)
        resp.raise_for_status()
        stations = resp.json().get('stations', [])

        existing = {stop.stop_id: stop for stop in DVBStop.objects.all()}
        seen_ids = set()
        to_create = []
        to_update = []
        for station in stations:
            stop_id = station.get('numeric_id')
            name = station.get('name')
            if not stop_id or not name:
                continue
            seen_ids.add(stop_id)
            city = station.get('city', '')
            current = existing.get(stop_id)
            if current is None:
                to_create.append(DVBStop(stop_id=stop_id, name=name, city=city))
            elif current.name != name or current.city != city:
                current.name = name
                current.city = city
                to_update.append(current)

        # This mirrors upstream exactly, including removals - even a stop a DVBView still
        # references gets dropped. Evaluated up front, before anything is deleted below: a bulk
        # delete's automatic M2M cleanup doesn't fire the usual m2m_changed reload signal, so the
        # displays that need reloading are captured here while the stop-view links still exist.
        stale_ids = existing.keys() - seen_ids
        affected_displays = displays_showing(DVBView.objects.filter(stops__stop_id__in=stale_ids).distinct())

        with transaction.atomic():
            DVBStop.objects.bulk_create(to_create, batch_size=500)
            DVBStop.objects.bulk_update(to_update, ['name', 'city'], batch_size=500)
            deleted_count = DVBStop.objects.filter(stop_id__in=stale_ids).delete()[0] if stale_ids else 0

        if stale_ids:
            affected_displays.reload()

        unchanged = len(stations) - len(to_create) - len(to_update)
        self.stdout.write(self.style.SUCCESS(
            f'DVB stops: {len(to_create)} created, {len(to_update)} updated, '
            f'{unchanged} unchanged, {deleted_count} removed'
        ))
