"""Operational metadata only: no customer paths, transcripts or command args."""
import json
import os
from streamlit.logger import get_logger

logger = get_logger('talking_video.delivery')


def record(event, **fields):
    logger.info('video_delivery %s', json.dumps(dict(event=event, **fields), ensure_ascii=False))


def exception_details(exc):
    # Exceptions may echo customer filenames; log the OS-provided explanation
    # rather than the user-controlled filename portion of str(exc).
    return dict(error_type=type(exc).__name__, errno=getattr(exc, 'errno', None),
        error=os.strerror(exc.errno) if isinstance(exc, OSError) and exc.errno else type(exc).__name__)
