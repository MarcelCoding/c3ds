from .base import *  # NoQa
from .base import INSTALLED_APPS, MIDDLEWARE
import datetime

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-!u%=5%b3-n*_l++m66=jtbk-4t=a5n5#qj-ifnv)g_xu_jp*01'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Datenspuren 2026 starts Friday Sep 11, 2026
DAY_ZERO = datetime.datetime(2026, 9, 11, 16, 0, 0)

# C3Nav map URL
C3NAV_BASE_URL = 'https://map.datenspuren.de'

# Django Debug Toolbar
with suppress(ImportError):
    import debug_toolbar  # NoQa
    INSTALLED_APPS.append('debug_toolbar')
    MIDDLEWARE.append('debug_toolbar.middleware.DebugToolbarMiddleware')

with suppress(ImportError):
    from .local import *  # NoQa