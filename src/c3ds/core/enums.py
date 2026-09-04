from enum import StrEnum


class DisplayCommands(StrEnum):
    PING = 'ping'
    PONG = 'pong'
    RELOAD = 'reload'
    NTP_REQUEST = 'NTPRequest'
    NTP_RESPONSE = 'NTPResponse'