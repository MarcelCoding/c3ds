import json
import logging
from datetime import datetime, UTC
from time import time_ns

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer
from django.core.cache import cache

from c3ds.core.enums import DisplayCommands
from c3ds.core.models import Display

logger = logging.getLogger(__name__)

class DisplayConsumer(WebsocketConsumer):
    def connect(self):
        self.display_slug = self.scope['url_route']['kwargs']['display_slug']
        self.display_group = f'display_{self.display_slug}'

        async_to_sync(self.channel_layer.group_add)(
            self.display_group, self.channel_name
        )
        async_to_sync(self.channel_layer.group_add)(
            'displays', self.channel_name
        )

        self.accept()

    def disconnect(self, close_code):
        pass

    def receive(self, text_data = None, bytes_data = None):
        data: dict[str] = json.loads(text_data)
        logger.debug('Received message: %s', text_data)

        match data.get('cmd', None):
            case 'ping':
                if not self.scope['user'].is_authenticated:
                    cache.set(Display.heartbeat_cache_key_for_slug(self.display_slug), datetime.now(tz=UTC), None)
                self.cmd({'cmd': 'pong'})
                self.check_content_version(data.get('version'))

            case 'NTPRequest':
                try:
                    self.cmd_data({'data': {
                        'cmd': 'NTPResponse',
                        'serverTime': time_ns() // 1000000,
                        'clientSendTimestamp': data['sendTimestamp'],
                    }})
                except KeyError:
                    logger.error('Received invalid NTPRequest')

            case 'NTPReport':
                try:
                    if not self.scope['user'].is_authenticated:
                        cache.set(Display.ntp_offset_cache_key_for_slug(self.display_slug), data['ntpOffset'], None)
                    logger.info('Received NTPReport, Offset: %0.3f ms, Latency: %0.3f ms',
                                data['ntpOffset'], data['ntpLatency'])
                except KeyError:
                    logger.error('Received invalid NTPReport')

    def check_content_version(self, version):
        """Reload a display that is rendering an older revision than the database holds.

        Reload commands only reach whoever is in the channel group at the time, so one sent while
        a display was reloading is gone for good. This is how it finds out.
        """
        if version is None:
            return
        try:
            display = Display.objects.get(slug=self.display_slug)
        except Display.DoesNotExist:
            return
        current = display.get_content_version()
        if current != version:
            logger.info('Display "%s" reports version %r, current is %r - telling it to reload',
                        self.display_slug, version, current)
            self.cmd({'cmd': DisplayCommands.RELOAD, 'delayed': False})

    def cmd(self, event):
        # Receive message from display group
        if not 'cmd' in event:
            raise ValueError('No command specified')
        cmd = event["cmd"]

        if isinstance(cmd, str):
            cmd = {'cmd': cmd}
        elif not isinstance(cmd, dict):
            raise TypeError('Invalid cmd object')

        logger.debug('Sending command: %s', cmd)
        # Send message to WebSocket
        self.send(text_data=json.dumps(cmd))

    def cmd_data(self, event):
        if not 'data' in event:
            raise ValueError('No command/data specified')

        self.send(text_data=json.dumps(event["data"]))
