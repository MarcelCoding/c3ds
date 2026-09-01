from django.conf import settings


def event_data(request):
    day_zero = settings.DAY_ZERO
    return {'event': {
        'day_zero': day_zero.isoformat() if day_zero else None,
    }}

def extra_data(request):
    ip_address = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0].strip()

    return {'extra_data': {
        'ip_address': ip_address,
    }}