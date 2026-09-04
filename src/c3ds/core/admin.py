import datetime

from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.http import HttpRequest
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from c3ds.core.models import (BaseView, DEFAULT_DISPLAY_DURATION, Display, DisplayQuerySet, HTMLView, IFrameView,
                              ImageFile, ImageView, Playlist, PlaylistEntry, RandomView, Schedule, ScheduleView,
                              displays_showing,
                              MastodonPost, MastodonPostView, VideoFile, VideoView)

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

    @admin.action(description=_('Reload Assigned Display(s)'))
    def reload(self, request: HttpRequest, queryset):
        # A view reaches a display through a playlist or a proxy too, and two of the selected
        # views can end up on the same display - collect the displays before reloading them.
        displays_showing(queryset).reload()


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


class PlaylistEntryForm(forms.ModelForm):
    class Meta:
        model = PlaylistEntry
        fields = ('view', 'order', 'display_duration')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The model keeps this nullable for historic rows, but a new entry must spell its duration out.
        self.fields['display_duration'].required = True
        self.fields['display_duration'].initial = DEFAULT_DISPLAY_DURATION


class PlaylistEntryInline(admin.TabularInline):
    model = PlaylistEntry
    form = PlaylistEntryForm
    extra = 1
    fields = ('view', 'order', 'display_duration')
    ordering = ('order',)


@admin.register(Playlist)
class PlaylistAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'last_changed')
    fields = ('name', 'slug', 'last_changed')
    readonly_fields = ('last_changed',)
    inlines = [PlaylistEntryInline]
