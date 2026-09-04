import datetime

import channels.layers
from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.db import models
from django.db.models import functions
from django.http import HttpRequest
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from c3ds.core.models import (BaseView, Display, DisplayQuerySet, HTMLView, IFrameView, ImageFile, ImageView, Playlist,
                              PlaylistEntry, RandomView, Schedule, ScheduleView, MastodonPost, MastodonPostView,
                              VideoFile, VideoView)

class SlugLinkMixin():
    slug_view = 'view_by_slug'

    def link(self, obj):
        if not obj.slug:
            return ''
        url = reverse(self.slug_view, kwargs={'slug': obj.slug})
        return mark_safe(f'<a href="{url}" target="_blank">view</a>')


@admin.register(Display)
class DisplayAdmin(admin.ModelAdmin, SlugLinkMixin):
    list_display = ['name', 'slug', 'static_view', 'playlist', 'link', 'c3nav', 'heartbeat']
    list_display.append('last_changed')
    slug_view = 'display_by_slug'

    fields = ('name', 'slug', 'static_view', 'playlist', 'link', 'c3nav', 'last_seen', 'last_changed')
    readonly_fields = ('link', 'c3nav', 'last_seen', 'last_changed')
    actions = ('reload', )

    def c3nav(self, obj):
        return mark_safe(f'<a href="{settings.C3NAV_BASE_URL}/l/{obj.slug.lower()}" target="_blank">map</a>')

    def heartbeat(self, obj: Display):
        last = cache.get(obj.get_heartbeat_cache_key())
        if last is None or not isinstance(last, datetime.datetime):
            return 'Unknown'
        else:
            if (datetime.datetime.now(tz=datetime.UTC) - last).total_seconds() < 60:
                return mark_safe('<span style="color: green;">Online</span>')
            else:
                return mark_safe('<span style="color: red;">Offline</span>')

    def last_seen(self, obj: Display):
        last = cache.get(obj.get_heartbeat_cache_key())
        if last is None or not isinstance(last, datetime.datetime):
            return 'Unknown'
        else:
            return last.strftime('%Y-%m-%d %H:%M')

    @admin.action(description=_('Reload Display(s)'))
    def reload(self, request: HttpRequest, queryset: DisplayQuerySet):
        queryset.reload()


class ViewAdmin(admin.ModelAdmin, SlugLinkMixin):
    actions = ('reload',)

    @admin.action(description=_('Reload Sssigned Display(s)'))
    def reload(self, request: HttpRequest, queryset):
        num_displays = queryset.annotate(num_displays = functions.Coalesce(models.Count('displays'), 0))\
            .aggregate(num_displays=models.Sum('num_displays', default=0))['num_displays']
        delayed = num_displays > settings.DELAYED_RELOAD_THRESHOLD
        for view in queryset.all():
            view.displays.reload(delayed)


@admin.register(HTMLView)
class HTMLViewAdmin(ViewAdmin):
    list_display = ('name', 'slug', 'title', 'link', 'last_changed')


@admin.register(IFrameView)
class IFrameViewAdmin(ViewAdmin):
    list_display = ('name', 'slug', 'title', 'layout_mode', 'url', 'link', 'last_changed')


@admin.register(ImageFile)
class ImageFileAdmin(admin.ModelAdmin):
    list_display = ('name', 'filename', 'file', 'file_link', 'last_changed')

    def file_link(self, obj) -> str:
        return mark_safe(f'<a href="{obj.file.url}" target="_blank" alt="{obj.name}">View</a>')


@admin.register(ImageView)
class ImageViewAdmin(ViewAdmin):
    list_display = ('name', 'slug', 'title', 'layout_mode', 'image', 'link', 'last_changed')


@admin.register(VideoFile)
class VideoFileAdmin(admin.ModelAdmin):
    list_display = ('name', 'filename', 'file', 'loop', 'file_link', 'last_changed')

    def file_link(self, obj) -> str:
        return mark_safe(f'<a href="{obj.file.url}" target="_blank" alt="{obj.name}">View</a>')


@admin.register(VideoView)
class VideoViewAdmin(ViewAdmin):
    list_display = ('name', 'slug', 'title', 'layout_mode', 'video', 'video_url', 'link', 'last_changed')


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ('name', 'version', 'last_changed')
    fields = ('name', 'url', 'uuid', 'version', 'etag', 'file', 'last_changed')
    readonly_fields = ('uuid', 'version', 'etag', 'file', 'last_changed')
    actions = ('update_schedule',)

    @admin.action(description=_('Update Schedule'))
    def update_schedule(self, request, queryset):
        for schedule in queryset:
            schedule.update_schedule()


@admin.register(ScheduleView)
class ScheduleViewAdmin(ViewAdmin):
    list_display = ('name', 'slug', 'title', 'layout_mode', 'schedule', 'room_filter', 'link', 'last_changed')


@admin.register(MastodonPost)
class MastodonPostAdmin(admin.ModelAdmin):
    list_display = ('name', 'hashtags', 'post_count', 'cached_posts', 'last_fetched', 'last_changed')
    readonly_fields = ('posts_data', 'last_fetched')
    actions = ('fetch_posts',)

    @admin.display(description=_('Cached Posts'))
    def cached_posts(self, obj: MastodonPost):
        return len(obj.posts_data or [])

    @admin.action(description=_('Fetch Posts from c3d2.social'))
    def fetch_posts(self, request, queryset):
        for post in queryset:
            post.fetch_posts()


@admin.register(MastodonPostView)
class MastodonPostViewAdmin(ViewAdmin):
    list_display = ('name', 'slug', 'title', 'layout_mode', 'mastodon_post', 'link', 'last_changed')


@admin.register(RandomView)
class RandomViewAdmin(ViewAdmin):
    list_display = ('name', 'slug', 'target_count', 'link', 'last_changed')
    # The picked view brings its own title and layout along, these would never be rendered.
    exclude = ('title', 'layout_mode')
    filter_horizontal = ('targets',)

    @admin.display(description=_('Views'))
    def target_count(self, obj: RandomView):
        return obj.targets.count()

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        # A view picking itself would never resolve, so do not offer it.
        object_id = request.resolver_match.kwargs.get('object_id')
        if db_field.name == 'targets' and object_id:
            kwargs['queryset'] = BaseView.objects.exclude(pk=object_id)
        return super().formfield_for_manytomany(db_field, request, **kwargs)


class PlaylistEntryInline(admin.TabularInline):
    model = PlaylistEntry
    extra = 1
    fields = ('view', 'order', 'display_duration')
    ordering = ('order',)


@admin.register(Playlist)
class PlaylistAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'last_changed')
    fields = ('name', 'slug', 'last_changed')
    readonly_fields = ('last_changed',)
    inlines = [PlaylistEntryInline]
