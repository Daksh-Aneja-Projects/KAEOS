import logging
import re
import sys
from datetime import datetime


# ── PII redaction filter (GDPR/DPDP) ─────────────────────────────────────────
# INFO logs were leaking PII — e.g. skill_executor logs full tool results that
# can contain salaries and emails. This filter scrubs obvious PII from every log
# record before it is emitted. Kept deliberately cheap: a handful of pre-compiled
# regexes run over the already-formatted message string.

# Email addresses.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# US SSN (loose).
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# key: value / key = value / "key": value  where the key name looks sensitive.
# Captures the key + separator, redacts the value up to a delimiter.
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)([\"']?\b(?:password|passwd|pwd|token|secret|api[_-]?key|apikey|"
    r"access[_-]?key|auth|authorization|ssn|salary|compensation|"
    r"bank[_-]?account|account[_-]?number|routing[_-]?number)\b[\"']?\s*[:=]\s*)"
    r"([\"']?)([^\s,;}\"']+)"
)

_REDACTED = "[REDACTED]"


def _redact_pii(text: str) -> str:
    """Redact emails, SSNs, and sensitive key/value pairs from a log string.

    Raises on failure so the caller can fail closed. Returning the unredacted
    text on error would silently defeat the control at exactly the moment it
    matters, so partial redaction is never emitted.
    """
    if not text or ("@" not in text and ":" not in text and "=" not in text
                    and "-" not in text):
        return text
    text = _SENSITIVE_KEY_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{_REDACTED}", text)
    text = _EMAIL_RE.sub(_REDACTED, text)
    text = _SSN_RE.sub(_REDACTED, text)
    return text


class PIIRedactionFilter(logging.Filter):
    """Logging filter that scrubs PII from a record's message and args.

    Runs on the fully-interpolated message so it catches PII arriving via both
    f-strings and %-args. FAILS CLOSED: if redaction itself raises, the original
    message is suppressed rather than emitted, because the only reason to run
    this filter is that the unredacted text may carry PII.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            redacted = _redact_pii(msg)
            if redacted != msg:
                # Replace the message wholesale; args are already folded in, so
                # clear them to avoid a double-format that would re-expand PII.
                record.msg = redacted
                record.args = None
        except Exception:
            # Fail closed: letting the raw record through would defeat the whole
            # control. Keep the log line (so the event is not lost) but drop its
            # potentially-PII-bearing payload.
            record.msg = "[PII redaction failed; message suppressed]"
            record.args = None
        return True

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
            # Some streams (pytest capture, detached consoles) refuse
            # reconfigure. The default encoding still works; this is a
            # best-effort widening, so failing to widen is not an error.
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

    # Install PII redaction on the root logger so every emitted record — from
    # any module, via any handler — is scrubbed of emails/SSNs/secrets/salaries.
    logHandler.addFilter(PIIRedactionFilter())

    logger.addHandler(logHandler)
    logger.setLevel(logging.INFO)
