from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from c3ds.core.models import (BaseView, Display, ImageFile, MastodonPost, Playlist, PlaylistEntry,
                              RandomView, Schedule, VideoFile, displays_showing)


@receiver(post_save, sender=Display)
def display_saved_handler(sender: Display, instance: Display, created: bool, updated_fields=None, **kwargs):
    previous_slug = getattr(instance, 'loaded_slug', None)
    if previous_slug and previous_slug != instance.slug:
        # The running display still listens on the slug it was loaded with; reaching it under the
        # new one alone would leave it sitting on the old page forever.
        Display.reload_by_slug(previous_slug)
    instance.loaded_slug = instance.slug
    instance.reload()


@receiver(post_save)
def view_saved_handler(sender: BaseView, instance: BaseView = None, created: bool = None, updated_fields=None, **kwargs):
    if not isinstance(instance, BaseView):
        return
    # Not instance.displays - that only covers displays showing it as their static view.
    instance.get_displays().reload()


@receiver(m2m_changed, sender=RandomView.targets.through)
def random_view_targets_changed_handler(sender, instance, action, **kwargs):
    if action not in ('post_add', 'post_remove', 'post_clear'):
        return
    # Changing what a proxy can pick changes what the displays behind it show.
    instance.get_displays().reload()


@receiver(post_save, sender=Playlist)
def playlist_changed_handler(sender, instance: Playlist, **kwargs):
    instance.displays.reload()


@receiver(post_save, sender=PlaylistEntry)
@receiver(post_delete, sender=PlaylistEntry)
def playlist_entry_changed_handler(sender, instance: PlaylistEntry, **kwargs):
    # Look the displays up by id: on a cascade delete the playlist row may already be gone.
    Display.objects.filter(playlist_id=instance.playlist_id).reload()


@receiver(post_save, sender=ImageFile)
def image_file_changed_handler(sender, instance: ImageFile, **kwargs):
    displays_showing(instance.image_views.all()).reload()


@receiver(post_save, sender=VideoFile)
def video_file_changed_handler(sender, instance: VideoFile, **kwargs):
    displays_showing(instance.video_views.all()).reload()


@receiver(post_save, sender=Schedule)
def schedule_changed_handler(sender, instance: Schedule, **kwargs):
    displays_showing(instance.schedule_views.all()).reload()


@receiver(post_save, sender=MastodonPost)
def mastodon_post_changed_handler(sender, instance: MastodonPost, **kwargs):
    displays_showing(instance.mastodon_post_views.all()).reload()
