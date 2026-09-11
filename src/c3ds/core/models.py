import datetime
import logging
import random
import re
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Optional, Self, Any
from urllib.parse import quote

import channels.layers
import requests
from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ImproperlyConfigured
from django.db import models, transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from c3ds.core.enums import DisplayCommands
from c3ds.utils.filesystem import check_directory

logger = logging.getLogger(__name__)
channel_layer = channels.layers.get_channel_layer()


class DisplayQuerySet(models.QuerySet):
    def reload(self, delayed: Optional[bool] = None):
        slugs = self.values_list('slug', flat=True)
        if delayed is None:
            delayed = len(slugs) >= settings.DELAYED_RELOAD_THRESHOLD
        for slug in slugs:
            self.model.reload_by_slug(slug, delayed)


class Display(models.Model):
    name = models.CharField(max_length=128, verbose_name=_('Display Name'))
    slug = models.SlugField(verbose_name=_('Display Slug'), unique=True)
    uuid = models.UUIDField(verbose_name=_('Display UUID'), default=uuid.uuid4, editable=False, unique=True)
    static_view = models.ForeignKey('BaseView', on_delete=models.PROTECT, verbose_name=_('Static View'), null=True, blank=True)
    playlist = models.ForeignKey('Playlist', on_delete=models.PROTECT, verbose_name=_('Playlist'), null=True, blank=True)
    last_changed = models.DateTimeField(verbose_name=_('Last Changed'), auto_now=True)
    created_at = models.DateTimeField(verbose_name=_('Created At'), auto_now_add=True)
    #: Bumped every time a reload goes out, so a display can tell whether it missed one.
    last_reloaded_at = models.DateTimeField(verbose_name=_('Last Reloaded At'), null=True, editable=False)
    #: How that reload was sent, so catching up on a missed one keeps it spread out.
    last_reload_delayed = models.BooleanField(default=False, editable=False)

    objects = DisplayQuerySet.as_manager()

    class Meta:
        verbose_name = _('Display')
        verbose_name_plural = _('Displays')
        default_related_name = 'displays'
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(static_view__isnull=True) ^ Q(playlist__isnull=True)),
                name='static_view_or_playlist'
            ),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        # Kept so a rename can also reach the display still listening on the old slug.
        instance.loaded_slug = instance.slug
        return instance

    def get_content_version(self) -> str:
        """Token for the revision this display should be showing.

        The page renders it and the display sends it back on every ping, which is how a display
        that was reloading - and therefore not in the channel group - finds out that it missed a
        reload command. Commands are fire-and-forget, nothing else would ever tell it.
        """
        if self.last_reloaded_at is None:
            return ''
        return str(int(self.last_reloaded_at.timestamp() * 1_000_000))

    @classmethod
    async def async_reload_by_slug(cls, slug: str, delayed: bool = False):
        await channel_layer.group_send(f'display_{slug}', {
            'type': 'cmd',
            'cmd': {
                'cmd': DisplayCommands.RELOAD,
                'delayed': delayed,
            }
        })

    @classmethod
    def reload_by_slug(cls, slug: str, delayed: bool = False):
        # A display re-reads the database the moment it gets this, so sending it from inside an open
        # transaction (every admin change form is wrapped in one) would make it render the state from
        # before the current save. Hold the command back until the data it should pick up is committed.
        # Outside a transaction on_commit() runs the callback right away.
        # Stamped inside the transaction so a page rendered after the commit already carries the
        # new version - a display that misses the command below then notices on its next ping.
        cls.objects.filter(slug=slug).update(last_reloaded_at=datetime.datetime.now(tz=datetime.UTC),
                                            last_reload_delayed=delayed)
        transaction.on_commit(lambda: async_to_sync(cls.async_reload_by_slug)(slug, delayed))

    def reload(self, delayed: bool = False):
        self.reload_by_slug(self.slug, delayed)

    @staticmethod
    def heartbeat_cache_key_for_slug(slug: str) -> str:
        return f'{slug}-heartbeat'

    def get_heartbeat_cache_key(self):
        return self.heartbeat_cache_key_for_slug(self.slug)

    @staticmethod
    def ntp_offset_cache_key_for_slug(slug: str) -> str:
        return f'{slug}-ntp-offset'

    def get_ntp_offset_cache_key(self):
        return self.ntp_offset_cache_key_for_slug(self.slug)


class MediaFile(models.Model):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    filename = models.CharField(max_length=128, verbose_name=_('Filename'))
    file = models.FileField(upload_to="uploads/%Y/%m/%d/")
    last_changed = models.DateTimeField(verbose_name=_('Last Changed'), auto_now=True)
    created_at = models.DateTimeField(verbose_name=_('Created At'), auto_now_add=True)

    class Meta:
        abstract: True
        ordering = ["name"]

    def __str__(self):
        return self.name

class ImageFile(MediaFile):

    display_duration = models.PositiveIntegerField(verbose_name=_('Display Duration'), default=6,
                                                   help_text=_('Duration in seconds'))
    class Meta:
        verbose_name = _('Image')
        verbose_name_plural = _('Images')


class VideoFile(MediaFile):

    loop = models.BooleanField(default=False, verbose_name=_('Loop Video'))

    class Meta:
        verbose_name = _('Video')
        verbose_name_plural = _('Videos')


#: Fallback for entries that neither carry a duration nor end on their own.
DEFAULT_DISPLAY_DURATION = 30

#: Seconds to wait on the upstream schedule server; the fetch holds a row lock while it runs.
SCHEDULE_FETCH_TIMEOUT = 10


class Playlist(models.Model):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    slug = models.SlugField(verbose_name=_('Slug'), unique=True)
    uuid = models.UUIDField(verbose_name=_('UUID'), default=uuid.uuid4, editable=False, unique=True)
    views = models.ManyToManyField('BaseView', verbose_name=_('Views'), related_name='playlists',
                                   through='PlaylistEntry')
    last_changed = models.DateTimeField(verbose_name=_('Last Changed'), auto_now=True)
    created_at = models.DateTimeField(verbose_name=_('Created At'), auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_items(self) -> list[dict[str, Any]]:
        """Every entry as ``{url, duration}``, in playback order."""
        return [entry.as_item() for entry in self.entries.select_related('view').order_by('order')]


class PlaylistEntry(models.Model):
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, verbose_name=_('Playlist'), related_name='entries')
    view = models.ForeignKey('BaseView', on_delete=models.PROTECT, verbose_name=_('View'), related_name='+')
    order = models.PositiveIntegerField(verbose_name=_('Order'))
    display_duration = models.PositiveIntegerField(
        verbose_name=_('Display Duration'), blank=True, null=True,
        help_text=_('Overrides the display duration of an item. (seconds) \n'
                    'If the item is a video and it\'s not set to loop, this setting will be ignored.')
    )

    def __str__(self):
        return f'{self.order}. {self.view}'

    def get_duration(self) -> Optional[int]:
        """Seconds to show this entry, or ``None`` to wait for it to report that it finished."""
        view = self.view.get_specific()
        if isinstance(view, VideoView) and view.plays_to_end:
            return None
        if self.display_duration:
            return self.display_duration
        if isinstance(view, ImageView):
            return view.image.display_duration
        return DEFAULT_DISPLAY_DURATION

    def as_item(self) -> dict[str, Any]:
        return {'url': self.view.get_absolute_url(), 'duration': self.get_duration()}


#: How deep a chain of proxy views may nest before we give up.
MAX_VIEW_RESOLVE_DEPTH = 5


def displays_showing(views) -> DisplayQuerySet:
    """Every display showing any of ``views``, each display listed once."""
    display_ids = {pk for view in views for pk in view.get_displays().values_list('pk', flat=True)}
    return Display.objects.filter(pk__in=display_ids)


class BaseView(models.Model):
    view = None
    template_name = None
    vue_module = None
    #: Set on views that pick new content per request, so their responses are never cached.
    varies_per_request = False

    class LayoutModes(models.TextChoices):
        NORMAL = 'normal', _('Normal')
        COVER = 'cover', _('Cover')
        FULLSCREEN = 'fullscreen', _('Full Screen')

    name = models.CharField(max_length=128, verbose_name=_('Name'))
    slug = models.SlugField(verbose_name=_('Slug'), unique=True)
    uuid = models.UUIDField(verbose_name=_('UUID'), default=uuid.uuid4, editable=False, unique=True)
    title = models.CharField(max_length=128, verbose_name=_('Title'), blank=True)
    layout_mode = models.CharField(verbose_name=_('Layout Mode'), max_length=32, choices=LayoutModes,
                                   default=LayoutModes.NORMAL)
    last_changed = models.DateTimeField(verbose_name=_('Last Changed'), auto_now=True)
    created_at = models.DateTimeField(verbose_name=_('Created At'), auto_now_add=True)

    class Meta:
        verbose_name = _('View')
        verbose_name_plural = _('Views')
        default_related_name = 'views'
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_template_name(self):
        if self.template_name:
            return self.template_name
        raise ImproperlyConfigured('Subclasses of BaseView must provide a template_name or override get_template_name')

    def get_vue_module(self):
        if self.vue_module:
            return self.vue_module
        raise ImproperlyConfigured('Subclasses of BaseView must provide a vue_module or override get_vue_module')

    def get_specific(self) -> Optional[Self]:
        for field in self._meta.get_fields():
            if not isinstance(field, models.OneToOneRel) or not field.parent_link:
                continue
            with suppress(ObjectDoesNotExist):
                return getattr(self, field.accessor_name)
        return None

    def resolve(self, _depth: int = 0) -> Optional['BaseView']:
        """The view actually rendered for this one. Proxies override this to pick a target."""
        return self

    def get_displays(self) -> 'DisplayQuerySet':
        """Every display showing this view: as its static view, through a playlist, or behind a proxy."""
        shown_by = {self.pk}
        frontier = shown_by
        # A proxy renders one of its targets, so a display showing the proxy also shows this view.
        for _ in range(MAX_VIEW_RESOLVE_DEPTH):
            frontier = set(RandomView.objects.filter(targets__in=frontier)
                           .exclude(pk__in=shown_by).values_list('pk', flat=True))
            if not frontier:
                break
            shown_by |= frontier
        return Display.objects.filter(
            Q(static_view__in=shown_by) | Q(playlist__entries__view__in=shown_by)
        ).distinct()

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("view_by_pk", kwargs={"pk": self.pk})

    def get_context(self) -> dict[str, Any]:
        return {}


class HTMLView(BaseView):
    content = models.TextField(verbose_name=_('HTML Content'), blank=True)
    context = models.JSONField(verbose_name=_('context'), default=dict, blank=True, null=True,
                               help_text=_('Extra data passed to the context'))
    template_name_override = models.CharField(max_length=128, verbose_name=_('Template Name'), blank=True, null=True)
    vue_module_override = models.CharField(max_length=128, verbose_name=_('Vue Module'), blank=True, null=True)

    class Meta:
        verbose_name = _('HTML View')
        verbose_name_plural = _('HTML Views')
        default_related_name = 'html_views'
        ordering = ["name"]

    def get_template_name(self):
        return self.template_name_override or 'core/html_views/generic.html'

    def get_vue_module(self):
        return self.vue_module_override or 'HTMLViewGeneric'

    def get_context(self) -> dict[str, Any]:
        if self.context:
            return self.context
        else:
            return {}


class IFrameView(BaseView):
    template_name = 'core/iframe_view.html'
    vue_module = 'IFrameView'
    url = models.URLField(verbose_name=_('iframe URL'))

    class Meta:
        verbose_name = _('Iframe View')
        verbose_name_plural = _('Iframe Views')
        default_related_name = 'iframe_views'
        ordering = ["name"]


class ImageView(BaseView):
    template_name = 'core/image_view.html'
    vue_module = 'ImageView'
    image = models.ForeignKey(ImageFile, on_delete=models.PROTECT, verbose_name=_('Image'))

    class Meta:
        verbose_name = _('Image View')
        verbose_name_plural = _('Image Views')
        default_related_name = 'image_views'
        ordering = ["name"]


class VideoView(BaseView):
    template_name = 'core/video_view.html'
    vue_module = 'VideoView'
    video = models.ForeignKey(VideoFile, on_delete=models.PROTECT, verbose_name=_('Video'), blank=True, null=True)
    video_url = models.URLField(verbose_name=_('Video URL'), blank=True, null=True,
                                help_text=_('Can also be a hls or dash stream.'))

    class Meta:
        verbose_name = _('Video View')
        verbose_name_plural = _('Video Views')
        default_related_name = 'video_views'
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(video__isnull=True) ^ Q(video_url__isnull=True)),
                name='video_file_or_video_url'
            ),
        ]

    @property
    def plays_to_end(self) -> bool:
        """Only a local, non-looping video stops on its own — streams and looping videos need a duration."""
        return bool(self.video) and not self.video.loop

    def get_video_src(self) -> str:
        if self.video_url:
            return self.video_url
        if self.video and self.video.file:
            return self.video.file.url
        return ''

    def get_video_type(self):
        suffix = self.get_video_src().rsplit('.', 1)[-1]
        match suffix:
            case 'm3u8':
                return 'application/x-mpegURL'
            case 'mpd':
                return 'application/dash+xml'
            case _:
                return f'video/{suffix}'


class Schedule(models.Model):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    uuid = models.UUIDField(verbose_name=_('UUID'), default=uuid.uuid4, editable=False, unique=True)
    url = models.URLField(verbose_name=_('URL'))
    version = models.CharField(max_length=256, verbose_name=_('Version'), editable=False, null=True, blank=True)
    etag = models.CharField(max_length=256, verbose_name='ETag', editable=False, null=True, blank=True)
    file = models.FileField(verbose_name=_('File'), upload_to='schedules/', null=True, blank=True)
    last_changed = models.DateTimeField(verbose_name=_('Last Changed'), auto_now=True)
    created_at = models.DateTimeField(verbose_name=_('Created At'), auto_now_add=True)

    class Meta:
        verbose_name = _('Schedule')
        verbose_name_plural = _('Schedules')
        default_related_name = 'schedules'
        ordering = ["name"]

    def __str__(self):
        return self.name

    def update_schedule(self, force: bool = False):
        if self.pk is None:
            raise ValueError('Save model first')
        file_time = None
        if self.file:
            with suppress(FileNotFoundError):
                file_time = datetime.datetime.fromtimestamp(Path(self.file.path).stat().st_mtime, datetime.UTC)\
                    .strftime('%a, %d %b %Y %H:%M:%S GMT')
        # Fetched before the transaction opens: the request may take SCHEDULE_FETCH_TIMEOUT seconds
        # and holding a row lock - and on SQLite the whole database - for that long blocks everyone.
        req = requests.get(self.url, headers={
            'Accept': 'application/json',
            'If-None-Match': self.etag,
            'If-Modified-Since': None if self.etag else file_time
        }, timeout=SCHEDULE_FETCH_TIMEOUT)
        if not force and req.status_code == 304:
            logger.info('Not updating schedule "%s" [%d], unchanged. (304)', self.name, self.pk)
            return
        req.raise_for_status()
        new_version = req.json()['schedule']['version']
        with transaction.atomic():
            # Re-read under the lock: another fetch may have stored this version while we waited.
            old_version = Schedule.objects.select_for_update().get(pk=self.pk).version
            if not force and old_version and old_version == new_version:
                logger.info('Not updating schedule "%s" [%d], unchanged. (Version)', self.name, self.pk)
                return
            if not self.file.name:
                self.file.name = f'schedules/schedule-{self.uuid}.json'
            # Opening the file for writing does not create its directory, and on a fresh install
            # nothing has created the schedules one yet.
            check_directory(Path(self.file.path).parent, parents=True)
            with self.file.open('wb') as fp:
                fp.write(req.content)
            self.etag = req.headers.get('ETag', None)
            self.version = new_version
            self.save()
            logger.info('Updated schedule "%s" [%d]: %s → %s', self.name, self.pk, old_version, new_version)

    @property
    def local_url(self) -> str:
        """URL of the cached schedule, or '' while it has never been fetched."""
        if not self.file:
            return ''
        return self.file.url


class ScheduleView(BaseView):
    template_name = 'core/schedule_view.html'
    vue_module = 'ScheduleView'
    schedule = models.ForeignKey(Schedule, on_delete=models.PROTECT, verbose_name=_('Schedule'))
    room_filter = models.CharField(max_length=256, verbose_name=_('Room Filter'), blank=True, null=True,
                                        help_text=_('Room filter for schedule as semicolon-separated list'))
    guid_filter = models.CharField(max_length=256, verbose_name=_('GUID Filter'), blank=True, null=True,
                                   help_text=_('GUID Room filter for schedule as semicolon-separated list'))
    duration_limit = models.PositiveIntegerField(verbose_name=_('Duration Limit'), blank=True, null=True,
                                                 help_text=_('Filter schedule entries longer than x minutes'))

    class Meta:
        verbose_name = _('Schedule View')
        verbose_name_plural = _('Schedule Views')
        default_related_name = 'schedule_views'
        ordering = ["name"]


#: A post advertising more mentions or hashtags than this reads as spam/boost-bait and is filtered out.
MASTODON_MAX_MENTIONS = 5
MASTODON_MAX_HASHTAGS = 5

#: A post this fresh may still be edited/deleted by its author, so it is kept out of the cache
#: until it clears this age.
MASTODON_MIN_AGE = datetime.timedelta(minutes=10)

#: Fetched per hashtag as a multiple of post_count, so enough posts survive the mention/hashtag
#: and minimum-age filters to fill the pool.
MASTODON_FETCH_LIMIT_MULTIPLIER = 4


def mastodon_created_at(post: dict[str, Any]) -> datetime.datetime:
    """``created_at`` of a Mastodon API post as an aware datetime; unparseable values sort last."""
    try:
        created_at = datetime.datetime.fromisoformat(post['created_at'])
    except (KeyError, TypeError, ValueError):
        return datetime.datetime.min.replace(tzinfo=datetime.UTC)
    return created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=datetime.UTC)


class MastodonPost(models.Model):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    uuid = models.UUIDField(verbose_name=_('UUID'), default=uuid.uuid4, editable=False, unique=True)
    hashtags = models.CharField(max_length=512, verbose_name=_('Hashtags'),
                                help_text=_('Comma or semicolon-separated list of hashtags, e.g. "datenspuren;c3sd"'))
    posts_data = models.JSONField(verbose_name=_('Posts Data'), default=list, blank=True,
                                  help_text=_('Cached posts, newest first.'))
    post_count = models.PositiveIntegerField(verbose_name=_('Cached Posts'), default=10,
                                             help_text=_('How many posts to cache and pick from.'))
    recent_window = models.PositiveIntegerField(verbose_name=_('Recent Window'), default=780,
                                                help_text=_('A post younger than this is shown exclusively. (seconds)'))
    last_fetched = models.DateTimeField(verbose_name=_('Last Fetched'), null=True, blank=True)
    last_changed = models.DateTimeField(verbose_name=_('Last Changed'), auto_now=True)
    created_at = models.DateTimeField(verbose_name=_('Created At'), auto_now_add=True)

    class Meta:
        verbose_name = _('Mastodon Post')
        verbose_name_plural = _('Mastodon Posts')
        default_related_name = 'mastodon_posts'
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_hashtags(self) -> list[str]:
        return [h.strip() for h in self.hashtags.replace(',', ';').split(';') if h.strip()]

    @staticmethod
    def _is_spammy(post: dict[str, Any]) -> bool:
        """Too many @mentions or #hashtags is a sign of boost-bait rather than an on-topic post."""
        return (len(post.get('mentions') or []) > MASTODON_MAX_MENTIONS
                or len(post.get('tags') or []) > MASTODON_MAX_HASHTAGS)

    def fetch_posts(self, force: bool = False):
        if self.pk is None:
            raise ValueError('Save model first')
        fetched = []
        for hashtag in self.get_hashtags():
            url = f'https://c3d2.social/api/v1/timelines/tag/{quote(hashtag)}'
            try:
                resp = requests.get(url, params={'limit': self.post_count * MASTODON_FETCH_LIMIT_MULTIPLIER},
                                    timeout=10)
                resp.raise_for_status()
                posts = resp.json()
            except Exception as e:
                logger.warning('Failed to fetch posts for hashtag "%s": %s', hashtag, e)
                continue
            if not isinstance(posts, list):
                logger.warning('Unexpected response for hashtag "%s": %r', hashtag, posts)
                continue
            fetched.extend({'hashtag': hashtag, **post}
                           for post in posts if isinstance(post, dict) and 'id' in post)
        # A post carrying several of the configured hashtags comes back once per hashtag request;
        # keep the first copy so it is labelled with the earliest hashtag it matched.
        by_id: dict[str, dict[str, Any]] = {}
        for post in fetched:
            by_id.setdefault(post['id'], post)
        newest_first = sorted(by_id.values(), key=mastodon_created_at, reverse=True)
        now = datetime.datetime.now(tz=datetime.UTC)
        # Spammy or too-fresh posts are never included, even if that leaves the pool smaller
        # than post_count.
        posts = [post for post in newest_first
                 if not self._is_spammy(post) and now - mastodon_created_at(post) >= MASTODON_MIN_AGE
                 ][:self.post_count]
        if not posts:
            logger.warning('No posts fetched for MastodonPost "%s" [%d], keeping the cached ones', self.name, self.pk)
            return
        fetched_at = datetime.datetime.now(tz=datetime.UTC)
        if posts == self.posts_data:
            # Stamped with update() rather than save(): saving fires the reload signal, and every
            # display showing these posts would reload itself for content it is already rendering.
            # The fetch runs on a timer, so that reload arrives out of nowhere.
            logger.info('Posts for MastodonPost "%s" [%d] are unchanged', self.name, self.pk)
            MastodonPost.objects.filter(pk=self.pk).update(last_fetched=fetched_at)
            self.last_fetched = fetched_at
            return
        self.posts_data = posts
        self.last_fetched = fetched_at
        self.save()
        logger.info('Cached %d posts for MastodonPost "%s" [%d]', len(posts), self.name, self.pk)

    def get_post_to_display(self) -> Optional[dict[str, Any]]:
        """The newest post while it is fresh, otherwise a random one out of the cache."""
        posts = self.posts_data or []
        if not posts:
            return None
        newest = posts[0]  # posts_data is stored newest-first
        age = datetime.datetime.now(tz=datetime.UTC) - mastodon_created_at(newest)
        if age <= datetime.timedelta(seconds=self.recent_window):
            return newest
        return random.choice(posts)


class MastodonPostView(BaseView):
    template_name = 'core/mastodon_post_view.html'
    vue_module = 'MastodonPostView'
    # get_context() picks a different post per request.
    varies_per_request = True
    mastodon_post = models.ForeignKey(MastodonPost, on_delete=models.PROTECT, verbose_name=_('Mastodon Post'))
    refresh_interval = models.PositiveIntegerField(verbose_name=_('Refresh Interval'), default=60,
                                                   help_text=_('Refresh interval in seconds'))

    class Meta:
        verbose_name = _('Mastodon Post View')
        verbose_name_plural = _('Mastodon Post Views')
        default_related_name = 'mastodon_post_views'
        ordering = ["name"]

    def get_context(self) -> dict[str, Any]:
        return {'post_data': self.mastodon_post.get_post_to_display()}


#: How many hours ahead the hourly forecast reaches, and the step between the points shown.
WEATHER_HOURLY_RANGE = 12
WEATHER_HOURLY_STEP = 2

#: How many calendar days (today included) the daily forecast summarises.
WEATHER_DAILY_RANGE = 3


class WeatherLocation(models.Model):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    uuid = models.UUIDField(verbose_name=_('UUID'), default=uuid.uuid4, editable=False, unique=True)
    latitude = models.DecimalField(max_digits=8, decimal_places=5, verbose_name=_('Latitude'))
    longitude = models.DecimalField(max_digits=8, decimal_places=5, verbose_name=_('Longitude'))
    #: Cached hourly readings from Bright Sky, each ``{timestamp, temperature, icon, precipitation}``.
    forecast_data = models.JSONField(verbose_name=_('Forecast Data'), default=list, blank=True)
    last_fetched = models.DateTimeField(verbose_name=_('Last Fetched'), null=True, blank=True)
    last_changed = models.DateTimeField(verbose_name=_('Last Changed'), auto_now=True)
    created_at = models.DateTimeField(verbose_name=_('Created At'), auto_now_add=True)

    class Meta:
        verbose_name = _('Weather Location')
        verbose_name_plural = _('Weather Locations')
        default_related_name = 'weather_locations'
        ordering = ["name"]

    def __str__(self):
        return self.name

    def fetch_forecast(self, force: bool = False):
        if self.pk is None:
            raise ValueError('Save model first')
        today = datetime.date.today()
        try:
            resp = requests.get('https://api.brightsky.dev/weather', params={
                'lat': str(self.latitude),
                'lon': str(self.longitude),
                'date': today.isoformat(),
                'last_date': (today + datetime.timedelta(days=WEATHER_DAILY_RANGE)).isoformat(),
                # Bright Sky returns UTC otherwise; the daily bucketing below needs local days.
                'tz': 'Europe/Berlin',
            }, timeout=10)
            resp.raise_for_status()
            records = resp.json().get('weather', [])
        except Exception as e:
            logger.warning('Failed to fetch forecast for WeatherLocation "%s" [%d]: %s', self.name, self.pk, e)
            return
        forecast = [
            {'timestamp': r['timestamp'], 'temperature': r.get('temperature'),
             'icon': r.get('icon'), 'precipitation': r.get('precipitation')}
            for r in records if r.get('timestamp')
        ]
        if not forecast:
            logger.warning('No forecast data for WeatherLocation "%s" [%d], keeping the cached one', self.name, self.pk)
            return
        fetched_at = datetime.datetime.now(tz=datetime.UTC)
        if forecast == self.forecast_data:
            # Stamped with update() rather than save(): saving fires the reload signal, and every
            # display showing this forecast would reload itself for content it is already rendering.
            # The fetch runs on a timer, so that reload arrives out of nowhere.
            logger.info('Forecast for WeatherLocation "%s" [%d] is unchanged', self.name, self.pk)
            WeatherLocation.objects.filter(pk=self.pk).update(last_fetched=fetched_at)
            self.last_fetched = fetched_at
            return
        self.forecast_data = forecast
        self.last_fetched = fetched_at
        self.save()
        logger.info('Cached %d forecast hours for WeatherLocation "%s" [%d]', len(forecast), self.name, self.pk)

    def _parsed_forecast(self) -> list[tuple[datetime.datetime, dict[str, Any]]]:
        parsed = []
        for record in self.forecast_data:
            try:
                timestamp = datetime.datetime.fromisoformat(record['timestamp'])
            except (KeyError, TypeError, ValueError):
                continue
            parsed.append((timestamp, record))
        return parsed

    def get_hourly_forecast(self) -> list[dict[str, Any]]:
        """The next WEATHER_HOURLY_RANGE hours, sampled every WEATHER_HOURLY_STEP hours."""
        parsed = self._parsed_forecast()
        if not parsed:
            return []
        now = datetime.datetime.now(tz=datetime.UTC)
        picks = []
        for step in range(1, WEATHER_HOURLY_RANGE // WEATHER_HOURLY_STEP + 1):
            target = now + datetime.timedelta(hours=WEATHER_HOURLY_STEP * step)
            _, record = min(parsed, key=lambda entry: abs((entry[0] - target).total_seconds()))
            picks.append(record)
        return picks

    def get_daily_forecast(self) -> list[dict[str, Any]]:
        """The next WEATHER_DAILY_RANGE calendar days, each summarised from its hours.

        Starting tomorrow: today is already covered, hour by hour, by ``get_hourly_forecast()``.
        """
        parsed = self._parsed_forecast()
        if not parsed:
            return []
        tomorrow = datetime.datetime.now(tz=datetime.UTC).date() + datetime.timedelta(days=1)
        by_date: dict[datetime.date, list[tuple[datetime.datetime, dict[str, Any]]]] = {}
        for entry in parsed:
            by_date.setdefault(entry[0].date(), []).append(entry)

        days = []
        for day in sorted(d for d in by_date if d >= tomorrow)[:WEATHER_DAILY_RANGE]:
            entries = by_date[day]
            temps = [record['temperature'] for _, record in entries if record.get('temperature') is not None]
            if not temps:
                continue
            precipitation = sum(record.get('precipitation') or 0 for _, record in entries)
            # The icon for the whole day: whichever hour sits closest to local noon.
            _, midday_record = min(entries, key=lambda entry: abs(entry[0].hour - 12))
            days.append({
                'date': day.isoformat(),
                'temp_min': min(temps),
                'temp_max': max(temps),
                'precipitation': round(precipitation, 1),
                'icon': midday_record.get('icon'),
            })
        return days


class WeatherView(BaseView):
    template_name = 'core/weather_view.html'
    vue_module = 'WeatherView'
    # The hourly/daily picks are derived from the wall clock, not from anything with its own version.
    varies_per_request = True
    location = models.ForeignKey(WeatherLocation, on_delete=models.PROTECT, verbose_name=_('Weather Location'))
    refresh_interval = models.PositiveIntegerField(verbose_name=_('Refresh Interval'), default=1800,
                                                   help_text=_('Refresh interval in seconds'))

    class Meta:
        verbose_name = _('Weather View')
        verbose_name_plural = _('Weather Views')
        default_related_name = 'weather_views'
        ordering = ["name"]

    def get_context(self) -> dict[str, Any]:
        return {
            'weather_data': {
                'hourly': self.location.get_hourly_forecast(),
                'daily': self.location.get_daily_forecast(),
            }
        }


#: Base URL for the VVO/DVB open data API (used by dvbpy/dvbjs).
DVB_BASE_URL = 'https://webapi.vvo-online.de'

#: Default number of upcoming departures to show for each stop.
DVB_DEPARTURES_PER_STOP = 7

#: Kept short: this runs synchronously in a page request, and several stops are fetched
#: sequentially, so a slow/unreachable API must not stack up into a slow page load.
DVB_REQUEST_TIMEOUT = 6

#: A line filter only keeps some of what the API returns, so enough matching departures must
#: survive out of a larger, unfiltered fetch to still fill departures_per_stop.
DVB_FILTER_FETCH_MULTIPLIER = 5

#: Matches the API's Microsoft-JSON date format, e.g. "/Date(1699999999000+0100)/".
DVB_DATE_RE = re.compile(r'/Date\((\d+)([+-]\d{4})?\)/')


def dvb_parse_date(value: Optional[str]) -> Optional[datetime.datetime]:
    """Parses a VVO API timestamp; ``None`` if missing or unparseable."""
    if not value:
        return None
    match = DVB_DATE_RE.match(value)
    if not match:
        return None
    return datetime.datetime.fromtimestamp(int(match.group(1)) / 1000, tz=datetime.UTC)


class DVBStop(models.Model):
    """A VVO stop, imported from the community-maintained stop directory.

    See the ``import_dvb_stops`` management command - rows here are not meant to be
    created by hand, the import command is what keeps ``stop_id`` correct.
    """
    stop_id = models.CharField(max_length=32, verbose_name=_('Stop ID'), unique=True)
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    city = models.CharField(max_length=128, verbose_name=_('City'), blank=True)
    last_changed = models.DateTimeField(verbose_name=_('Last Changed'), auto_now=True)
    created_at = models.DateTimeField(verbose_name=_('Created At'), auto_now_add=True)

    class Meta:
        verbose_name = _('DVB Stop')
        verbose_name_plural = _('DVB Stops')
        default_related_name = 'dvb_stops'
        ordering = ['city', 'name']

    def __str__(self):
        return f'{self.name} ({self.city})' if self.city else self.name


def _split_filter_list(value: str) -> list[str]:
    return [item.strip() for item in value.replace(',', ';').split(';') if item.strip()]


class DVBViewStop(models.Model):
    """A stop assigned to a DVBView, with optional per-stop line/destination filters.

    A plain M2M can't tell two views' shared stop apart, but the same line can run through
    several stops a view shows - e.g. tram 3 passing both "Zeithainer Straße" and "Liststraße" -
    so which lines/destinations to show has to live on this assignment, not on the stop or view alone.
    """
    view = models.ForeignKey('DVBView', on_delete=models.CASCADE, related_name='stop_entries')
    stop = models.ForeignKey(DVBStop, on_delete=models.CASCADE, related_name='view_entries')
    excluded_lines = models.CharField(max_length=256, verbose_name=_('Excluded Lines'), blank=True,
                                      help_text=_('Hide these lines at this stop, semicolon-separated '
                                                  '(e.g. "3;7") - useful when a line also stops nearby '
                                                  'and is shown at that other stop instead. Leave blank '
                                                  'to show every line.'))
    excluded_destinations = models.CharField(max_length=256, verbose_name=_('Excluded Destinations'), blank=True,
                                             help_text=_('Hide vehicles with these final destinations at this '
                                                         'stop, semicolon-separated (e.g. "Btf. Trachenberge") - '
                                                         'useful for a depot-only run nobody can actually board. '
                                                         'Leave blank to show every destination.'))
    walking_minutes = models.PositiveIntegerField(verbose_name=_('Walking Minutes'), default=0,
                                                  help_text=_('Minutes it takes to walk to this stop. Departures '
                                                              'leaving sooner than this are hidden, since nobody '
                                                              'could reach the stop in time. Leave at 0 to show '
                                                              'every departure.'))

    class Meta:
        verbose_name = _('DVB View Stop')
        verbose_name_plural = _('DVB View Stops')
        constraints = [
            models.UniqueConstraint(fields=['view', 'stop'], name='dvb_view_stop_unique'),
        ]

    def __str__(self):
        return f'{self.stop} @ {self.view}'

    def get_excluded_lines(self) -> list[str]:
        return _split_filter_list(self.excluded_lines)

    def get_excluded_destinations(self) -> list[str]:
        return _split_filter_list(self.excluded_destinations)


class DVBView(BaseView):
    template_name = 'core/dvb_view.html'
    vue_module = 'DVBView'
    # Departures are fetched live from the VVO API on every request.
    varies_per_request = True
    stops = models.ManyToManyField(DVBStop, verbose_name=_('Stops'), blank=True,
                                   through='DVBViewStop', related_name='dvb_views')
    departures_per_stop = models.PositiveIntegerField(verbose_name=_('Departures per Stop'),
                                                      default=DVB_DEPARTURES_PER_STOP,
                                                      help_text=_('How many upcoming departures to show for each stop.'))
    refresh_interval = models.PositiveIntegerField(verbose_name=_('Refresh Interval'), default=60,
                                                   help_text=_('Refresh interval in seconds'))

    class Meta:
        verbose_name = _('DVB View')
        verbose_name_plural = _('DVB Views')
        default_related_name = 'dvb_views'
        ordering = ["name"]

    def fetch_departures(self) -> list[dict[str, Any]]:
        """Live departures for every configured stop, each ``{stop_name, departures}``."""
        results = []
        now = datetime.datetime.now(tz=datetime.UTC)
        for entry in self.stop_entries.select_related('stop').all():
            stop = entry.stop
            excluded_lines = entry.get_excluded_lines()
            excluded_destinations = entry.get_excluded_destinations()
            walking_minutes = entry.walking_minutes
            stop_name = f'{stop.name} ({walking_minutes}min)' if walking_minutes else stop.name
            # Over-fetch when filtering by line/destination/walking time: enough departures must
            # survive the filtering out of the raw, unfiltered list the API returns.
            fetch_limit = self.departures_per_stop * DVB_FILTER_FETCH_MULTIPLIER \
                if excluded_lines or excluded_destinations or walking_minutes else self.departures_per_stop
            try:
                resp = requests.post(f'{DVB_BASE_URL}/dm', json={
                    'stopid': stop.stop_id,
                    'limit': fetch_limit,
                    'format': 'json',
                }, timeout=DVB_REQUEST_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning('Failed to fetch departures for DVBStop "%s" [%d]: %s', stop, stop.pk, e)
                results.append({'stop_name': stop_name, 'departures': [], 'error': True})
                continue
            departures = []
            for dep in data.get('Departures') or []:
                scheduled = dvb_parse_date(dep.get('ScheduledTime'))
                if scheduled is None:
                    continue
                line = dep.get('LineName', '')
                direction = dep.get('Direction', '')
                if line in excluded_lines or direction in excluded_destinations:
                    continue
                real_time = dvb_parse_date(dep.get('RealTime'))
                departure_time = real_time or scheduled
                if (departure_time - now) < datetime.timedelta(minutes=walking_minutes):
                    continue
                departures.append({
                    'line': line,
                    'direction': direction,
                    'scheduled': scheduled.isoformat(),
                    'real_time': real_time.isoformat() if real_time else None,
                    'state': dep.get('State', ''),
                    'platform': (dep.get('Platform') or {}).get('Name'),
                    'mode': dep.get('Mot', ''),
                })
                if len(departures) >= self.departures_per_stop:
                    break
            results.append({'stop_name': stop_name, 'departures': departures})
        return results

    def get_context(self) -> dict[str, Any]:
        return {'dvb_data': {'stops': self.fetch_departures()}}


class RandomView(BaseView):
    #: Only rendered when nothing can be picked; normally a target's own template is used.
    template_name = 'core/random_view.html'
    vue_module = 'RandomView'
    varies_per_request = True
    targets = models.ManyToManyField(BaseView, verbose_name=_('Views'), blank=True,
                                     related_name='random_views',
                                     help_text=_('One of these is picked at random every time '
                                                 'this view is shown.'))

    class Meta:
        verbose_name = _('Random View')
        verbose_name_plural = _('Random Views')
        default_related_name = 'random_views_set'
        ordering = ["name"]

    def save(self, *args, **kwargs):
        # Not editable: the picked view brings its own, and the empty fallback should stay blank.
        self.layout_mode = self.LayoutModes.FULLSCREEN
        super().save(*args, **kwargs)

    def resolve(self, _depth: int = 0) -> Optional[BaseView]:
        if _depth >= MAX_VIEW_RESOLVE_DEPTH:
            logger.warning('Random View "%s" [%d] nests deeper than %d levels, showing nothing',
                           self.name, self.pk, MAX_VIEW_RESOLVE_DEPTH)
            return None
        # A view pointing at itself would recurse forever.
        candidates = [view for view in self.targets.all() if view.pk != self.pk]
        if not candidates:
            logger.warning('Random View "%s" [%d] has no views to pick from', self.name, self.pk)
            return None
        chosen = random.choice(candidates).get_specific()
        return chosen.resolve(_depth + 1) if chosen is not None else None
