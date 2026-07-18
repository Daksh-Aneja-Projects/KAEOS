import logging
import sys
from datetime import datetime

try:
    from pythonjsonlogger import jsonlogger

    class CustomJsonFormatter(jsonlogger.JsonFormatter):
        def add_fields(self, log_record, record, message_dict):
            super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
            if not log_record.get('timestamp'):
                now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                log_record['timestamp'] = now
            if log_record.get('level'):
                log_record['level'] = log_record['level'].upper()
            else:
                log_record['level'] = record.levelname

    _HAS_JSON_LOGGER = True

except ImportError:
    _HAS_JSON_LOGGER = False


def setup_logging():
    logger = logging.getLogger()
    # Remove existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Windows consoles often default to cp1252, which crashes on emoji in log
    # messages ("--- Logging error --- UnicodeEncodeError"). Force UTF-8 with
    # replacement so a log line can never take down the logging pipeline.
    stream = sys.stderr
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    logHandler = logging.StreamHandler(stream)

    if _HAS_JSON_LOGGER:
        formatter = CustomJsonFormatter('%(timestamp)s %(level)s %(name)s %(message)s')
        logHandler.setFormatter(formatter)
    else:
        # Fallback: structured text logging when pythonjsonlogger is not installed
        formatter = logging.Formatter(
            fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%dT%H:%M:%S'
        )
        logHandler.setFormatter(formatter)

    logger.addHandler(logHandler)
    logger.setLevel(logging.INFO)
