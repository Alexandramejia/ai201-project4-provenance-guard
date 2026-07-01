import json
import os
from datetime import datetime, timezone

LOG_FILE = "audit_log.json"


def _read_log():
    """Load the audit log list from disk, or return an empty list."""
    if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
        return []

    with open(LOG_FILE, "r") as f:
        return json.load(f)


def _write_log(entries):
    """Save the audit log list back to disk."""
    with open(LOG_FILE, "w") as f:
        json.dump(entries, f, indent=2)


def log_submission(content_id, creator_id, attribution, confidence, llm_score, style_score, status):
    """Append one /submit decision to the audit log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": llm_score,
        "style_score": style_score,
        "status": status,
    }

    entries = _read_log()
    entries.append(entry)
    _write_log(entries)

    return entry


def log_appeal(content_id, creator_reasoning):
    """Append one creator appeal to the audit log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "content_id": content_id,
        "creator_reasoning": creator_reasoning,
        "status": "under_review",
        "event_type": "appeal",
    }

    entries = _read_log()
    entries.append(entry)
    _write_log(entries)

    return entry


def get_log_entries():
    """Return every entry currently stored in the audit log."""
    return _read_log()
