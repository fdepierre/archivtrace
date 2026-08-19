"""Date/time helpers used for run identifiers and file names."""

from __future__ import annotations

from datetime import datetime, timezone


def now() -> datetime:
    """Timezone-aware current time (UTC)."""
    return datetime.now(timezone.utc)


def today_slug(moment: datetime | None = None) -> str:
    """Return the date as `YYYY-MM-DD`, used as a file-name prefix."""
    return (moment or now()).strftime("%Y-%m-%d")


def iso(moment: datetime | None = None) -> str:
    """Return an ISO-8601 timestamp (seconds precision)."""
    return (moment or now()).replace(microsecond=0).isoformat()


def run_id(moment: datetime | None = None) -> str:
    """Compact, sortable run identifier, e.g. `20260628T145122Z`."""
    moment = moment or now()
    return moment.strftime("%Y%m%dT%H%M%SZ")
