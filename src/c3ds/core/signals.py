import channels.layers
from asgiref.sync import async_to_sync
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from c3ds.core.models import BaseView, Display, Playlist, PlaylistEntry


channel_layer = channels.layers.get_channel_layer()


@receiver(post_save, sender=Display)
def display_saved_handler(sender: Display, instance: Display, created: bool, updated_fields=None, **kwargs):
    instance.reload()

@receiver(post_save)
def view_saved_handler(sender: BaseView, instance: BaseView = None, created: bool = None, updated_fields=None, **kwargs):
    if not isinstance(instance, BaseView):
        return
    instance.displays.reload()


@receiver(post_save, sender=Playlist)
@receiver(post_delete, sender=Playlist)
def playlist_changed_handler(sender, instance: Playlist, **kwargs):
    instance.displays.reload()


@receiver(post_save, sender=PlaylistEntry)
@receiver(post_delete, sender=PlaylistEntry)
def playlist_entry_changed_handler(sender, instance: PlaylistEntry, **kwargs):
    # Look the displays up by id: on a cascade delete the playlist row may already be gone.
    Display.objects.filter(playlist_id=instance.playlist_id).reload()
