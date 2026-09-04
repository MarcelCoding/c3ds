import json
from typing import Optional

from django.http import Http404
from django.utils.cache import add_never_cache_headers
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import DetailView

from c3ds.core.models import BaseView, Display


# Playlists render their entries in an iframe.
@method_decorator(xframe_options_sameorigin, name='dispatch')
class GenericView(DetailView):
    model = BaseView
    context_object_name = 'view'
    #: Set when the requested view delegated rendering to another one.
    proxy_source: Optional[BaseView] = None

    def get_object(self, queryset=None):
        obj = super().get_object(queryset).get_specific()
        resolved = obj.resolve()
        if resolved is None:
            # Nothing to delegate to - render the proxy itself, which falls back to an empty slide.
            self.proxy_source = obj
            return obj
        if resolved is not obj:
            self.proxy_source = obj
        return resolved

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        view = getattr(self, 'object', None)
        if self.proxy_source is not None or getattr(view, 'varies_per_request', False):
            # These pick new content per request, so the response must never be cached.
            add_never_cache_headers(response)
        return response

    def get_template_names(self):
        return [self.object.get_template_name()]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            'view': self.object,
            'layout_mode': getattr(self.object, 'layout_mode', 'normal'),
            'slug': 'undefined',
        })
        ctx.update(self.object.get_context())
        return ctx





class DisplayView(DetailView):
    model = Display
    context_object_name = 'display'
    is_unconfigured = False
    _view = None

    def get_queryset(self):
        return super().get_queryset().select_related('playlist', 'static_view')

    def get_object(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()

        try:
            obj = super().get_object(queryset=queryset)
        except (queryset.model.DoesNotExist, Http404):
            obj = None
            self.is_unconfigured = True
        return obj

    def get_template_names(self):
        if self.is_unconfigured:
            return ['core/display_unconfigured_view.html']
        elif self.object.static_view is not None:
            return [self.get_view().get_template_name()]
        elif self.object.playlist is not None:
            return ['core/playlist_view.html']
        else:
            return ['core/display_unconfigured_view.html']


    def get_view(self) -> Optional[BaseView]:
        if self.is_unconfigured or self.object is None:
            return None
        if self.object.static_view is None:
            return None
        if self._view is None:
            specific = self.object.static_view.get_specific()
            # An unresolvable proxy falls back to rendering itself, so we always have a view here.
            self._view = specific.resolve() or specific
        return self._view

    def get_layout_mode(self):
        # Playlist entries are rendered in their own frame, each with its own layout mode.
        if self.object is not None and self.object.playlist is not None:
            return BaseView.LayoutModes.FULLSCREEN
        view = self.get_view()
        return getattr(view, 'layout_mode', 'normal') if view is not None else 'normal'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        view = self.get_view()
        ctx.update({
            'view': view,
            'layout_mode': self.get_layout_mode(),
            'slug': self.kwargs.get(self.slug_url_kwarg)
        })
        if view is not None:
            ctx.update(view.get_context())

        if self.object is not None and self.object.playlist is not None:
            ctx['playlist_json'] = json.dumps(self.object.playlist.get_items())

        return ctx
