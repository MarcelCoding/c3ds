from unittest import mock

from django.test import TestCase

from c3ds.core.models import Display, HTMLView, Playlist, PlaylistEntry, RandomView


class ReloadFanOutTests(TestCase):
    """Saving a view has to reload every display that shows it, however it got there."""

    def setUp(self):
        self.view = HTMLView.objects.create(name='Shown', slug='shown')

    def reloaded_slugs(self, func):
        """The slugs the displays got a reload command for while ``func`` ran."""
        sent = []
        with mock.patch.object(Display, 'async_reload_by_slug',
                               new=mock.AsyncMock(side_effect=lambda slug, delayed=False: sent.append(slug))):
            with self.captureOnCommitCallbacks(execute=True):
                func()
        return set(sent)

    def test_static_view_display_is_reloaded(self):
        Display.objects.create(name='Static', slug='static-display', static_view=self.view)

        self.assertEqual(self.reloaded_slugs(self.view.save), {'static-display'})

    def test_playlist_display_is_reloaded(self):
        playlist = Playlist.objects.create(name='List', slug='list')
        PlaylistEntry.objects.create(playlist=playlist, view=self.view, order=0)
        Display.objects.create(name='Playlist', slug='playlist-display', playlist=playlist)

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
