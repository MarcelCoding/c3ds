import datetime
import logging
import random
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
        cls.objects.filter(slug=slug).update(last_reloaded_at=datetime.datetime.now(tz=datetime.UTC))
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

    def get_view(self):
        raise NotImplementedError()
        # ToDo: implement view loading

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
    recent_window = models.PositiveIntegerField(verbose_name=_('Recent Window'), default=180,
                                                help_text=_('A post younger than this is always shown. (seconds)'))
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

    def fetch_posts(self, force: bool = False):
        if self.pk is None:
            raise ValueError('Save model first')
        fetched = []
        for hashtag in self.get_hashtags():
            url = f'https://c3d2.social/api/v1/timelines/tag/{quote(hashtag)}'
            try:
                resp = requests.get(url, params={'limit': self.post_count}, timeout=10)
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
        posts = sorted(by_id.values(), key=mastodon_created_at, reverse=True)[:self.post_count]
        if not posts:
            logger.warning('No posts fetched for MastodonPost "%s" [%d], keeping the cached ones', self.name, self.pk)
            return
        self.posts_data = posts
        self.last_fetched = datetime.datetime.now(tz=datetime.UTC)
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
