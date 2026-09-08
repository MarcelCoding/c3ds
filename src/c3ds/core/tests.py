import datetime
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings

from c3ds.core.build import get_build_id
from c3ds.core.models import (Display, HTMLView, ImageFile, ImageView, MastodonPost, MastodonPostView,
                              Playlist, PlaylistEntry, RandomView, Schedule, ScheduleView, VideoFile, VideoView,
                              WeatherLocation, WeatherView)
from c3ds.urls import websocket_urlpatterns


class ReloadCaptureMixin:
    def reloaded_slugs(self, func):
        """The slugs that got a reload command while ``func`` ran."""
        sent = []
        with mock.patch.object(Display, 'async_reload_by_slug',
                               new=mock.AsyncMock(side_effect=lambda slug, delayed=False: sent.append(slug))):
            with self.captureOnCommitCallbacks(execute=True):
                func()
        return set(sent)


class DelayedReloadTests(ReloadCaptureMixin, TestCase):
    """Past the threshold displays must be told to spread their reloads, not all reload at once."""

    def reload_commands(self, func):
        sent = []
        with mock.patch.object(Display, 'async_reload_by_slug',
                               new=mock.AsyncMock(side_effect=lambda slug, delayed=False: sent.append(delayed))):
            with self.captureOnCommitCallbacks(execute=True):
                func()
        return sent

    def show_on(self, count):
        view = HTMLView.objects.create(name='V', slug='v')
        playlist = Playlist.objects.create(name='P', slug='p')
        PlaylistEntry.objects.create(playlist=playlist, view=view, order=0)
        for i in range(count):
            Display.objects.create(name=f'D{i}', slug=f'd{i}', playlist=playlist)
        return view

    @override_settings(DELAYED_RELOAD_THRESHOLD=3)
    def test_a_change_reaching_many_displays_asks_them_to_spread_out(self):
        view = self.show_on(3)

        self.assertEqual(self.reload_commands(view.save), [True, True, True])

    @override_settings(DELAYED_RELOAD_THRESHOLD=3)
    def test_a_change_reaching_few_displays_reloads_them_at_once(self):
        view = self.show_on(2)

        self.assertEqual(self.reload_commands(view.save), [False, False])


class ReloadFanOutTests(ReloadCaptureMixin, TestCase):
    """Saving anything a display renders has to reload that display, however it got there."""

    def setUp(self):
        self.view = HTMLView.objects.create(name='Shown', slug='shown')

    def show_in_playlist(self, view, slug='playlist-display'):
        playlist = Playlist.objects.create(name=f'List {slug}', slug=f'list-{slug}')
        PlaylistEntry.objects.create(playlist=playlist, view=view, order=0)
        return Display.objects.create(name=slug, slug=slug, playlist=playlist)

    def test_static_view_display_is_reloaded(self):
        Display.objects.create(name='Static', slug='static-display', static_view=self.view)

        self.assertEqual(self.reloaded_slugs(self.view.save), {'static-display'})

    def test_playlist_display_is_reloaded(self):
        self.show_in_playlist(self.view)

        self.assertEqual(self.reloaded_slugs(self.view.save), {'playlist-display'})

    def test_display_behind_a_random_view_is_reloaded(self):
        proxy = RandomView.objects.create(name='Proxy', slug='proxy')
        proxy.targets.add(self.view)
        Display.objects.create(name='Proxied', slug='proxy-display', static_view=proxy)

        self.assertEqual(self.reloaded_slugs(self.view.save), {'proxy-display'})

    def test_unrelated_display_is_not_reloaded(self):
        other = HTMLView.objects.create(name='Other', slug='other')
        Display.objects.create(name='Other', slug='other-display', static_view=other)

        self.assertEqual(self.reloaded_slugs(self.view.save), set())

    def test_adding_a_target_to_a_random_view_reloads_its_displays(self):
        proxy = RandomView.objects.create(name='Proxy', slug='proxy')
        Display.objects.create(name='Proxied', slug='proxy-display', static_view=proxy)

        self.assertEqual(self.reloaded_slugs(lambda: proxy.targets.add(self.view)), {'proxy-display'})

    def test_saving_an_image_file_reloads_displays_showing_it(self):
        image = ImageFile.objects.create(name='Pic', filename='pic.png', file='uploads/pic.png')
        self.show_in_playlist(ImageView.objects.create(name='IV', slug='iv', image=image))

        self.assertEqual(self.reloaded_slugs(image.save), {'playlist-display'})

    def test_saving_a_video_file_reloads_displays_showing_it(self):
        video = VideoFile.objects.create(name='Clip', filename='clip.mp4', file='uploads/clip.mp4')
        self.show_in_playlist(VideoView.objects.create(name='VV', slug='vv', video=video))

        self.assertEqual(self.reloaded_slugs(video.save), {'playlist-display'})

    def test_saving_a_schedule_reloads_displays_showing_it(self):
        schedule = Schedule.objects.create(name='Sched', url='https://example.invalid/s.json')
        self.show_in_playlist(ScheduleView.objects.create(name='SV', slug='sv', schedule=schedule))

        self.assertEqual(self.reloaded_slugs(schedule.save), {'playlist-display'})

    def test_saving_a_mastodon_post_reloads_displays_showing_it(self):
        post = MastodonPost.objects.create(name='Toots', hashtags='c3d2')
        self.show_in_playlist(MastodonPostView.objects.create(name='MV', slug='mv', mastodon_post=post))

        self.assertEqual(self.reloaded_slugs(post.save), {'playlist-display'})

    def test_renaming_a_display_also_reloads_the_slug_it_used_before(self):
        display = Display.objects.create(name='D', slug='before', static_view=self.view)
        display = Display.objects.get(pk=display.pk)

        def rename():
            display.slug = 'after'
            display.save()

        self.assertEqual(self.reloaded_slugs(rename), {'before', 'after'})


class ContentVersionTests(ReloadCaptureMixin, TestCase):
    """A display carries a token saying which revision of its content it is rendering."""

    def setUp(self):
        self.view = HTMLView.objects.create(name='Shown', slug='shown')
        self.display = Display.objects.create(name='D', slug='d', static_view=self.view)

    def current_version(self):
        return Display.objects.get(pk=self.display.pk).get_content_version()

    def test_version_changes_when_a_reload_is_issued(self):
        before = self.current_version()

        self.reloaded_slugs(self.view.save)

        self.assertNotEqual(before, self.current_version())

    def test_version_is_stable_while_nothing_changes(self):
        self.assertEqual(self.current_version(), self.current_version())


class DisplayConsumerTests(TransactionTestCase):
    """A display that missed a reload while it was disconnected finds out when it says hello."""

    async def connect(self, slug):
        communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), f'/ws/display/{slug}/')
        communicator.scope['user'] = AnonymousUser()
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        return communicator

    async def ping(self, communicator, version):
        await communicator.send_json_to({'cmd': 'ping', 'version': version})
        replies = []
        while not await communicator.receive_nothing(timeout=0.3):
            replies.append(await communicator.receive_json_from())
        return replies

    async def make_display(self, slug='d'):
        view = await sync_to_async(HTMLView.objects.create)(name='V', slug='v')
        return await sync_to_async(Display.objects.create)(name='D', slug=slug, static_view=view)

    async def catch_up_reload(self, slug='d'):
        """The reload a display gets back when it reports a version that is out of date."""
        communicator = await self.connect(slug)
        try:
            replies = await self.ping(communicator, 'a-version-from-before')
        finally:
            await communicator.disconnect()
        return next((r for r in replies if r['cmd'] == 'reload'), None)

    async def test_ping_with_a_stale_version_gets_a_reload(self):
        display = await sync_to_async(Display.objects.create)(
            name='D', slug='d', static_view=await sync_to_async(HTMLView.objects.create)(name='V', slug='v'))
        communicator = await self.connect('d')

        self.assertIn('reload', [r['cmd'] for r in await self.ping(communicator, 'a-version-from-before')])

        await communicator.disconnect()

    async def test_ping_with_the_current_version_is_only_answered_with_a_pong(self):
        display = await sync_to_async(Display.objects.create)(
            name='D', slug='d', static_view=await sync_to_async(HTMLView.objects.create)(name='V', slug='v'))
        version = await sync_to_async(lambda: Display.objects.get(slug='d').get_content_version())()
        communicator = await self.connect('d')

        self.assertEqual([r['cmd'] for r in await self.ping(communicator, version)], ['pong'])

        await communicator.disconnect()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CatchUpUrgencyTests(TransactionTestCase):
    """The catch-up must repeat how the missed command was sent, or it defeats the spreading."""

    async def connect(self, slug):
        communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), f'/ws/display/{slug}/')
        communicator.scope['user'] = AnonymousUser()
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        return communicator

    async def ping_for_reload(self, slug):
        communicator = await self.connect(slug)
        try:
            await communicator.send_json_to({'cmd': 'ping', 'version': 'a-version-from-before'})
            replies = []
            while not await communicator.receive_nothing(timeout=0.3):
                replies.append(await communicator.receive_json_from())
        finally:
            await communicator.disconnect()
        return next((r for r in replies if r['cmd'] == 'reload'), None)

    async def test_catching_up_on_a_spread_reload_is_spread_too(self):
        await sync_to_async(Display.objects.create)(
            name='D', slug='d', static_view=await sync_to_async(HTMLView.objects.create)(name='V', slug='v'))
        await sync_to_async(Display.reload_by_slug)('d', True)

        self.assertEqual((await self.ping_for_reload('d'))['delayed'], True)

    async def test_catching_up_on_an_immediate_reload_stays_immediate(self):
        await sync_to_async(Display.objects.create)(
            name='D', slug='d', static_view=await sync_to_async(HTMLView.objects.create)(name='V', slug='v'))
        await sync_to_async(Display.reload_by_slug)('d', False)

        self.assertEqual((await self.ping_for_reload('d'))['delayed'], False)


class ScheduleFetchTests(TransactionTestCase):
    """TransactionTestCase: a TestCase wraps the test in a transaction and would mask this."""

    def test_the_upstream_fetch_does_not_hold_a_transaction_open(self):
        schedule = Schedule.objects.create(name='S', url='https://example.invalid/s.json')
        in_transaction = []

        def fake_get(*args, **kwargs):
            in_transaction.append(connection.in_atomic_block)
            response = mock.Mock(status_code=200, content=b'{"schedule": {"version": "1"}}', headers={})
            response.json.return_value = {'schedule': {'version': '1'}}
            response.raise_for_status.return_value = None
            return response

        with mock.patch('c3ds.core.models.requests.get', side_effect=fake_get):
            schedule.update_schedule()

        self.assertEqual(in_transaction, [False])


class MastodonFetchTests(ReloadCaptureMixin, TestCase):
    """The posts are re-fetched on a timer, so a fetch bringing nothing new must not reload."""

    POSTS = [
        {'id': '2', 'created_at': '2026-09-08T12:00:00+00:00', 'content': 'newer'},
        {'id': '1', 'created_at': '2026-09-08T11:00:00+00:00', 'content': 'older'},
    ]

    def setUp(self):
        self.post = MastodonPost.objects.create(name='Toots', hashtags='c3d2')
        playlist = Playlist.objects.create(name='List', slug='list')
        PlaylistEntry.objects.create(
            playlist=playlist, order=0,
            view=MastodonPostView.objects.create(name='MV', slug='mv', mastodon_post=self.post))
        Display.objects.create(name='D', slug='playlist-display', playlist=playlist)

    def fetch(self, posts):
        # Re-read so the cached posts come back through the JSON field, as they do on a timer run.
        post = MastodonPost.objects.get(pk=self.post.pk)
        response = mock.Mock(status_code=200)
        response.json.return_value = posts
        response.raise_for_status.return_value = None
        with mock.patch('c3ds.core.models.requests.get', return_value=response):
            post.fetch_posts()

    def test_a_fetch_bringing_new_posts_reloads_the_displays_showing_them(self):
        self.assertEqual(self.reloaded_slugs(lambda: self.fetch(self.POSTS)), {'playlist-display'})

    def test_a_fetch_bringing_back_the_cached_posts_reloads_nothing(self):
        self.fetch(self.POSTS)

        self.assertEqual(self.reloaded_slugs(lambda: self.fetch(self.POSTS)), set())

    def test_a_fetch_bringing_back_the_cached_posts_still_records_the_attempt(self):
        self.fetch(self.POSTS)
        MastodonPost.objects.filter(pk=self.post.pk).update(last_fetched=None)

        self.fetch(self.POSTS)

        self.assertIsNotNone(MastodonPost.objects.get(pk=self.post.pk).last_fetched)


class BuildIdTests(SimpleTestCase):
    """The page carries the build it was rendered from, so a deploy can be told from a blip."""

    def build_id_for(self, files: dict[str, str]) -> str:
        with tempfile.TemporaryDirectory() as static_root:
            for name, content in files.items():
                path = Path(static_root) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            get_build_id.cache_clear()
            try:
                with override_settings(STATIC_ROOT=static_root):
                    return get_build_id()
            finally:
                get_build_id.cache_clear()

    def test_a_rebuilt_manifest_gets_a_different_id(self):
        before = self.build_id_for({'.vite/manifest.json': '{"main.ts": {"file": "main-1111.js"}}'})
        after = self.build_id_for({'.vite/manifest.json': '{"main.ts": {"file": "main-2222.js"}}'})

        self.assertNotEqual(before, after)

    def test_the_same_manifest_gets_the_same_id(self):
        files = {'.vite/manifest.json': '{"main.ts": {"file": "main-1111.js"}}'}

        self.assertEqual(self.build_id_for(files), self.build_id_for(files))

    def test_a_rewritten_staticfiles_manifest_gets_a_different_id(self):
        before = self.build_id_for({'staticfiles.json': '{"paths": {"a.css": "a.1111.css"}}'})
        after = self.build_id_for({'staticfiles.json': '{"paths": {"a.css": "a.2222.css"}}'})

        self.assertNotEqual(before, after)

    def test_uncollected_assets_get_no_id_at_all(self):
        """The dev server serves them unhashed, and nothing there should be told to reload."""
        self.assertEqual(self.build_id_for({}), '')


class BuildIdCheckTests(TransactionTestCase):
    """After a deploy a display is still running the old JS, and the ping is where that surfaces."""

    async def ping(self, build, version):
        communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), '/ws/display/d/')
        communicator.scope['user'] = AnonymousUser()
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        replies = []
        try:
            await communicator.send_json_to({'cmd': 'ping', 'version': version, 'build': build})
            while not await communicator.receive_nothing(timeout=0.3):
                replies.append(await communicator.receive_json_from())
        finally:
            await communicator.disconnect()
        return replies

    async def make_display(self):
        view = await sync_to_async(HTMLView.objects.create)(name='V', slug='v')
        await sync_to_async(Display.objects.create)(name='D', slug='d', static_view=view)
        return await sync_to_async(lambda: Display.objects.get(slug='d').get_content_version())()

    async def test_a_page_from_an_older_build_is_told_to_reload(self):
        version = await self.make_display()

        with mock.patch('c3ds.core.consumer.get_build_id', return_value='the-current-build'):
            replies = await self.ping('the-build-before', version)

        self.assertIn('reload', [r['cmd'] for r in replies])

    async def test_catching_up_on_a_deploy_is_spread_out(self):
        """Every display is behind at once after a deploy, so they must not all come back together."""
        version = await self.make_display()

        with mock.patch('c3ds.core.consumer.get_build_id', return_value='the-current-build'):
            replies = await self.ping('the-build-before', version)

        self.assertEqual(next(r for r in replies if r['cmd'] == 'reload')['delayed'], True)

    async def test_a_page_from_the_current_build_is_only_answered_with_a_pong(self):
        version = await self.make_display()

        with mock.patch('c3ds.core.consumer.get_build_id', return_value='the-current-build'):
            replies = await self.ping('the-current-build', version)

        self.assertEqual([r['cmd'] for r in replies], ['pong'])

    async def test_a_display_without_a_build_id_is_left_alone(self):
        """Nothing was collected, so there is no build to be behind."""
        version = await self.make_display()

        with mock.patch('c3ds.core.consumer.get_build_id', return_value=''):
            replies = await self.ping('', version)

        self.assertEqual([r['cmd'] for r in replies], ['pong'])


class ReloadAllDisplaysTests(ReloadCaptureMixin, TestCase):
    """Reloading the fleet by hand has to leave the same trace behind that an edit does."""

    def setUp(self):
        self.display = Display.objects.create(
            name='D', slug='d', static_view=HTMLView.objects.create(name='V', slug='v'))

    def run_command(self):
        call_command('reload_all_displays', stdout=StringIO())

    def current_version(self):
        return Display.objects.get(pk=self.display.pk).get_content_version()

    def test_every_display_is_reloaded(self):
        Display.objects.create(
            name='D2', slug='d2', static_view=HTMLView.objects.create(name='W', slug='w'))

        self.assertEqual(self.reloaded_slugs(self.run_command), {'d', 'd2'})

    def test_the_version_is_bumped_so_a_display_that_missed_it_finds_out(self):
        before = self.current_version()

        self.reloaded_slugs(self.run_command)

        self.assertNotEqual(before, self.current_version())

    def test_the_fleet_is_told_to_spread_out(self):
        sent = []
        with mock.patch.object(Display, 'async_reload_by_slug',
                               new=mock.AsyncMock(side_effect=lambda slug, delayed=False: sent.append(delayed))):
            with self.captureOnCommitCallbacks(execute=True):
                self.run_command()

        self.assertEqual(sent, [True])


class WeatherFetchTests(ReloadCaptureMixin, TestCase):
    """The forecast is re-fetched on a timer, so a fetch bringing nothing new must not reload."""

    def response_for(self, hourly):
        response = mock.Mock(status_code=200)
        response.json.return_value = {'weather': hourly}
        response.raise_for_status.return_value = None
        return response

    def setUp(self):
        self.location = WeatherLocation.objects.create(name='Dresden', latitude='51.05', longitude='13.74')
        playlist = Playlist.objects.create(name='List', slug='list')
        PlaylistEntry.objects.create(
            playlist=playlist, order=0,
            view=WeatherView.objects.create(name='WV', slug='wv', location=self.location))
        Display.objects.create(name='D', slug='playlist-display', playlist=playlist)

    def fetch(self, hourly):
        # Re-read so the cached forecast comes back through the JSON field, as it does on a timer run.
        location = WeatherLocation.objects.get(pk=self.location.pk)
        with mock.patch('c3ds.core.models.requests.get', return_value=self.response_for(hourly)):
            location.fetch_forecast()

    def test_a_fetch_bringing_a_new_forecast_reloads_the_displays_showing_it(self):
        hourly = [{'timestamp': '2026-09-08T12:00:00+02:00', 'temperature': 18.0,
                  'icon': 'clear-day', 'precipitation': 0.0}]

        self.assertEqual(self.reloaded_slugs(lambda: self.fetch(hourly)), {'playlist-display'})

    def test_a_fetch_bringing_back_the_cached_forecast_reloads_nothing(self):
        hourly = [{'timestamp': '2026-09-08T12:00:00+02:00', 'temperature': 18.0,
                  'icon': 'clear-day', 'precipitation': 0.0}]
        self.fetch(hourly)

        self.assertEqual(self.reloaded_slugs(lambda: self.fetch(hourly)), set())

    def test_a_fetch_bringing_back_the_cached_forecast_still_records_the_attempt(self):
        hourly = [{'timestamp': '2026-09-08T12:00:00+02:00', 'temperature': 18.0,
                  'icon': 'clear-day', 'precipitation': 0.0}]
        self.fetch(hourly)
        WeatherLocation.objects.filter(pk=self.location.pk).update(last_fetched=None)

        self.fetch(hourly)

        self.assertIsNotNone(WeatherLocation.objects.get(pk=self.location.pk).last_fetched)

    def test_a_fetch_bringing_nothing_keeps_the_cached_forecast(self):
        self.fetch([{'timestamp': '2026-09-08T12:00:00+02:00', 'temperature': 18.0,
                     'icon': 'clear-day', 'precipitation': 0.0}])

        self.fetch([])

        self.assertEqual(len(WeatherLocation.objects.get(pk=self.location.pk).forecast_data), 1)


class WeatherForecastAggregationTests(TestCase):
    """The picks are derived from the wall clock, so the fixtures are built relative to it."""

    def build_location(self, hours_back=24, hours_ahead=100):
        now = datetime.datetime.now(tz=datetime.UTC)
        offsets = range(-hours_back, hours_ahead)
        forecast = [{
            'timestamp': (now + datetime.timedelta(hours=offset)).isoformat(),
            'temperature': float(offset),
            'icon': f'hour-{offset}',
            'precipitation': 1.0,
        } for offset in offsets]
        location = WeatherLocation.objects.create(name='Dresden', latitude='51.05', longitude='13.74',
                                                  forecast_data=forecast)
        return location, now, offsets

    def test_hourly_forecast_samples_every_two_hours_for_the_next_twelve(self):
        location, now, _offsets = self.build_location()

        hourly = location.get_hourly_forecast()

        self.assertEqual([h['temperature'] for h in hourly], [2.0, 4.0, 6.0, 8.0, 10.0, 12.0])

    def test_daily_forecast_starts_tomorrow_and_covers_three_calendar_days(self):
        """Today is already covered, hour by hour, by the hourly forecast."""
        location, now, offsets = self.build_location()
        tomorrow = now.date() + datetime.timedelta(days=1)

        daily = location.get_daily_forecast()

        self.assertEqual([d['date'] for d in daily],
                         [(tomorrow + datetime.timedelta(days=i)).isoformat() for i in range(3)])
        for i, day in enumerate(daily):
            day_date = tomorrow + datetime.timedelta(days=i)
            day_offsets = [o for o in offsets if (now + datetime.timedelta(hours=o)).date() == day_date]
            self.assertEqual(day['temp_min'], float(min(day_offsets)))
            self.assertEqual(day['temp_max'], float(max(day_offsets)))
            self.assertEqual(day['precipitation'], round(len(day_offsets) * 1.0, 1))
            closest_to_noon = min(day_offsets, key=lambda o: abs((now + datetime.timedelta(hours=o)).hour - 12))
            self.assertEqual(day['icon'], f'hour-{closest_to_noon}')

    def test_an_empty_cache_yields_no_picks(self):
        location = WeatherLocation.objects.create(name='Dresden', latitude='51.05', longitude='13.74')

        self.assertEqual(location.get_hourly_forecast(), [])
        self.assertEqual(location.get_daily_forecast(), [])
