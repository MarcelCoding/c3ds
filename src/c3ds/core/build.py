"""Identifier for the frontend build this process serves."""
import hashlib
import logging
from functools import lru_cache
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

#: Rewritten by every deploy, and identical for every process serving the same one.
ASSET_MANIFESTS = ('.vite/manifest.json', 'staticfiles.json')


@lru_cache(maxsize=1)
def get_build_id() -> str:
    """Token for the built assets, or '' when none have been collected.

    A display echoes this on every ping, which is how it finds out that its page came from an
    earlier deploy than the one now being served: the content version only tracks the database,
    so new templates or scripts would otherwise never reach a display that just keeps running.

    Read once per process. The files cannot change without a restart bringing the new ones in,
    and a display must not see the id flip while it is connected.
    """
    digest = hashlib.sha256()
    hashed = []
    for name in ASSET_MANIFESTS:
        try:
            digest.update((Path(settings.STATIC_ROOT) / name).read_bytes())
        except OSError:
            continue
        hashed.append(name)
    if not hashed:
        # The dev server serves the assets unbuilt and replaces them in place, so there is no
        # build to be behind - and nothing to tell anyone to reload for.
        logger.info('No asset manifest under %s, running without a build id', settings.STATIC_ROOT)
        return ''
    build_id = digest.hexdigest()[:32]
    logger.info('Serving frontend build %s (hashed %s)', build_id, ', '.join(hashed))
    return build_id
