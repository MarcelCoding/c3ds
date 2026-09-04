import tempfile
from unittest import mock

from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings

from c3ds.core.models import (Display, HTMLView, ImageFile, ImageView, MastodonPost, MastodonPostView,
                              Playlist, PlaylistEntry, RandomView, Schedule, ScheduleView, VideoFile, VideoView)
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
            replies.append((await communicator.receive_json_from())['cmd'])
        return replies

    async def test_ping_with_a_stale_version_gets_a_reload(self):
        display = await sync_to_async(Display.objects.create)(
            name='D', slug='d', static_view=await sync_to_async(HTMLView.objects.create)(name='V', slug='v'))
        communicator = await self.connect('d')

        self.assertIn('reload', await self.ping(communicator, 'a-version-from-before'))

        await communicator.disconnect()

    async def test_ping_with_the_current_version_is_only_answered_with_a_pong(self):
        display = await sync_to_async(Display.objects.create)(
            name='D', slug='d', static_view=await sync_to_async(HTMLView.objects.create)(name='V', slug='v'))
        version = await sync_to_async(lambda: Display.objects.get(slug='d').get_content_version())()
        communicator = await self.connect('d')

        self.assertEqual(await self.ping(communicator, version), ['pong'])

        await communicator.disconnect()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
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
