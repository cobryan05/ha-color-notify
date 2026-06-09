"""Data models for ColorNotify notification sequences."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import contextlib
from copy import copy
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .const import OFF_RGB
from .utils.light_sequence import ColorInfo, LightSequence

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NotificationConfig:
    """Immutable configuration for a notification sequence."""

    priority: int
    notify_id: str | None
    pattern: list[str | ColorInfo]
    peek_enabled: bool
    clear_delay: float | None

    def __post_init__(self) -> None:
        """Copy the mutable pattern list so callers can't mutate the config after construction."""
        # frozen=True prevents normal assignment; use object.__setattr__ instead.
        object.__setattr__(self, "pattern", list(self.pattern))


class ActiveNotification:
    """An active notification with mutable priority and runtime animation state."""

    def __init__(self, config: NotificationConfig) -> None:
        """Initialize the active notification from config."""
        self.priority: int = config.priority
        self._config = config
        self._sequence: LightSequence = LightSequence()
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._color: ColorInfo = ColorInfo(OFF_RGB, 0)
        self._step_finished: asyncio.Event = asyncio.Event()
        self._step_finished.set()
        self._initial_hold_sec: float = 0.0
        self.reset()

    def __repr__(self) -> str:
        """Return debug string."""
        return f"Animation Pri: {self.priority} Sequence: {self._sequence}"

    @property
    def peek_enabled(self) -> bool:
        """Return True if this notification can be peek-boosted."""
        return self._config.peek_enabled

    @property
    def color(self) -> ColorInfo:
        """Return a copy of the current animation color."""
        return copy(self._color)

    @property
    def notify_id(self) -> str | None:
        """Return the notify_id from config."""
        return self._config.notify_id

    @property
    def clear_delay(self) -> float | None:
        """Return the clear_delay from config."""
        return self._config.clear_delay

    @property
    def loops_forever(self) -> bool:
        """Return True if the animation loops indefinitely."""
        return self._sequence.loops_forever

    def wait(self) -> Coroutine:
        """Return a coroutine that resolves when the current animation step finishes."""
        return self._step_finished.wait()

    def reset(self) -> None:
        """Reset the sequence to the beginning."""
        self._sequence = LightSequence.create_from_pattern(self._config.pattern)
        self._color = (
            self._sequence.color
            if self._sequence.color is not None
            else ColorInfo(OFF_RGB, 0)
        )

    def set_initial_hold(self, seconds: float) -> None:
        """Set extra hold time for the first color step (e.g. bulb warm-up)."""
        self._initial_hold_sec = seconds

    async def _worker_func(
        self,
        stop_event: asyncio.Event,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Coroutine to run the animation until finished or interrupted."""
        done = False
        self.reset()
        hold_delay = self._initial_hold_sec
        try:
            while not done and not stop_event.is_set():
                self._step_finished.clear()
                done = await self._sequence.runNextStep()
                if not stop_event.is_set():
                    self._color = self._sequence.color
                if hold_delay > 0 and not stop_event.is_set():
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(stop_event.wait(), timeout=hold_delay)
                    hold_delay = 0
                self._step_finished.set()
        except Exception:
            _LOGGER.exception("Failed running NotificationAnimation")
        finally:
            # Ensure the work loop is never left waiting on a cleared event.
            self._step_finished.set()
        # Fire autoclear callback instead of calling hass.services directly.
        if self._config.clear_delay == 0 and on_complete is not None:
            on_complete()

    async def run(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Start the animation background task."""
        if self._stop_event:
            self._stop_event.set()
        self._stop_event = asyncio.Event()
        self._color = self._sequence.color
        self._task = config_entry.async_create_background_task(
            hass,
            self._worker_func(self._stop_event, on_complete),
            name="Animation worker",
        )

    async def stop(self) -> None:
        """Stop the animation."""
        if self._stop_event:
            self._stop_event.set()

    def is_running(self) -> bool:
        """Return True if the animation task is currently running."""
        return bool(
            self._task
            and not self._task.done()
            and self._stop_event
            and not self._stop_event.is_set()
        )
