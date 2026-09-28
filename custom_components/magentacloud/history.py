"""Persist usage samples used by MagentaCLOUD change sensors."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .api import MagentaCloudData

_STORAGE_VERSION = 1
_MAX_AGE = timedelta(days=32)
# One regular 30-minute poll plus five minutes of scheduling/network jitter.
# Never use a newer sample to make an incomplete history appear complete.
_BASELINE_TOLERANCE = timedelta(minutes=35)
_LOGGER = logging.getLogger(__name__)


class UsageHistory:
    """Store quota samples and calculate rolling changes."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[list[dict[str, Any]]] = Store(
            hass, _STORAGE_VERSION, f"magentacloud.{entry_id}.history"
        )
        self._samples: list[dict[str, Any]] = []
        self._can_save = True
        self._save_failed = False

    async def async_load(self) -> None:
        """Load previously recorded samples."""
        try:
            loaded = await self._store.async_load()
        except Exception:
            # History is optional. Do not overwrite an unreadable store with an
            # empty history; keep collecting in memory until the next reload.
            self._can_save = False
            _LOGGER.warning(
                "Usage history could not be loaded; using memory only until "
                "integration reload. Cloud polling continues"
            )
            return

        if loaded is None:
            return
        if not isinstance(loaded, list):
            self._can_save = False
            _LOGGER.warning(
                "Usage history has an invalid format; preserving the stored "
                "data and using memory only until integration reload"
            )
            return

        samples = []
        for sample in loaded:
            try:
                if not isinstance(sample, dict):
                    raise ValueError
                used = sample["used"]
                if type(used) is not int or used < 0:
                    raise ValueError
                timestamp = datetime.fromisoformat(sample["timestamp"])
                if timestamp.utcoffset() is None:
                    raise ValueError
                samples.append({
                    "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
                    "used": used,
                })
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        if len(samples) != len(loaded):
            # Retain valid samples in memory, but preserve the original file for
            # recovery rather than silently replacing it with partial data.
            self._can_save = False
            _LOGGER.warning(
                "Ignoring invalid usage history entries; preserving stored "
                "data and using memory only until integration reload"
            )
        self._samples = samples

    async def async_enrich(self, data: MagentaCloudData) -> MagentaCloudData:
        """Add rolling changes and persist the newest sample."""
        now = data.last_success.astimezone(timezone.utc)
        cutoff = now - _MAX_AGE
        self._samples = [
            sample
            for sample in self._samples
            if cutoff <= datetime.fromisoformat(sample["timestamp"]) <= now
        ]

        daily = self._change_since(now - timedelta(days=1), data.used)
        monthly = self._change_since(now - timedelta(days=30), data.used)
        self._samples.append({"timestamp": now.isoformat(), "used": data.used})
        if self._can_save:
            try:
                await self._store.async_save(list(self._samples))
            except Exception:
                # CancelledError deliberately propagates: unloading HA must
                # never be delayed by this optional persistence layer.
                if not self._save_failed:
                    _LOGGER.warning(
                        "Usage history could not be saved; keeping samples in "
                        "memory. Cloud polling continues; next update retries"
                    )
                self._save_failed = True
            else:
                if self._save_failed:
                    _LOGGER.info("Usage history persistence recovered")
                self._save_failed = False

        return MagentaCloudData(
            used=data.used,
            available=data.available,
            last_success=data.last_success,
            latency_ms=data.latency_ms,
            daily_change=daily,
            monthly_change=monthly,
        )

    def _change_since(self, target: datetime, current: int) -> int | None:
        """Return net change only if a sufficiently close baseline exists.

        Targets are UTC instants: 24 hours and 30 * 24 hours, not calendar
        day/month boundaries. Intermediate samples are not needed for a net
        difference, but a missing baseline must not expand the time window.
        """
        candidates = [
            sample
            for sample in self._samples
            if target - _BASELINE_TOLERANCE
            <= datetime.fromisoformat(sample["timestamp"]) <= target
        ]
        if not candidates:
            return None
        baseline = max(
            candidates, key=lambda sample: datetime.fromisoformat(sample["timestamp"])
        )
        return current - int(baseline["used"])
