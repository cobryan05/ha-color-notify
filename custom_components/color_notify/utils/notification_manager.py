"""Priority notification queue manager for ColorNotify."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_DELAY,
    CONF_DELAY_TIME,
    SERVICE_TURN_OFF,
    STATE_OFF,
    STATE_ON,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from ..const import (
    CONF_PEEK_TIME,
    CONF_WARMUP_TIME,
    INIT_STATE_UPDATE_DELAY_SEC,
    MAXIMUM_PRIORITY,
)
from ..models import ActiveNotification
from ..utils.light_sequence import ColorInfo

if TYPE_CHECKING:
    from ..sensor import ColorNotifyLogEntity

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Typed queue command dataclasses — replace the old tagged-union _QueueEntry
# ---------------------------------------------------------------------------


@dataclass
class _AddCommand:
    notify_id: str
    notification: ActiveNotification
    log_trigger: str | None = None


@dataclass
class _DeleteCommand:
    notify_id: str
    log_trigger: str | None = None


@dataclass
class _WakeCommand:
    log_trigger: str | None = None


@dataclass
class _CycleSameCommand:
    log_trigger: str | None = None


type _QueueCommand = _AddCommand | _DeleteCommand | _WakeCommand | _CycleSameCommand


# ---------------------------------------------------------------------------
# NotificationManager
# ---------------------------------------------------------------------------


class NotificationManager:
    """Owns the priority queue, work loop, and sequence lifecycle.

    Constructed in NotificationLightEntity.__init__ (before hass is set).
    Call start() from async_added_to_hass to spawn the background task.
    Call stop() from async_will_remove_from_hass to cancel it.
    """

    def __init__(
        self,
        config_entry: ConfigEntry,
        get_hass: Callable[[], HomeAssistant],
        wrapped_entity_id: str,
        on_color_change: Callable[..., Awaitable[bool]],
        event_logger: ColorNotifyLogEntity | None,
        entity_name: str,
    ) -> None:
        """Initialize the notification manager."""
        self._config_entry = config_entry
        self._get_hass = get_hass
        self._wrapped_entity_id = wrapped_entity_id
        self._on_color_change = on_color_change
        self._event_logger = event_logger
        self._entity_name = entity_name

        self._active_sequences: dict[str, ActiveNotification] = {}
        self._running_sequences: dict[str, ActiveNotification] = {}
        self._last_set_color: ColorInfo | None = None
        self._task_queue: asyncio.Queue[_QueueCommand] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Spawn the background worker task. Call from async_added_to_hass."""
        hass = self._get_hass()
        self._task = self._config_entry.async_create_background_task(
            hass,
            self._worker_func(),
            name=f"{self._entity_name} background task",
        )

    def stop(self) -> None:
        """Cancel the background worker task. Call from async_will_remove_from_hass."""
        if self._task:
            self._task.cancel()

    # ------------------------------------------------------------------
    # Public queue API
    # ------------------------------------------------------------------

    async def add_notification(
        self,
        notify_id: str,
        notification: ActiveNotification,
        log_trigger: str | None = None,
    ) -> None:
        """Enqueue a new notification sequence."""
        await self._task_queue.put(
            _AddCommand(
                notify_id=notify_id,
                notification=notification,
                log_trigger=log_trigger,
            )
        )

    async def remove_notification(
        self, notify_id: str, log_trigger: str | None = None
    ) -> None:
        """Enqueue removal of a notification sequence."""
        await self._task_queue.put(
            _DeleteCommand(notify_id=notify_id, log_trigger=log_trigger)
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @callback
    def _sort_active_sequences(self) -> None:
        self._active_sequences = dict(
            sorted(
                self._active_sequences.items(),
                key=lambda item: -item[1].priority,
            )
        )

    @callback
    def _get_top_sequences(self) -> list[ActiveNotification]:
        """Return the list of top-priority active sequences."""
        ret: list[ActiveNotification] = []
        top_prio: int = 0
        for sequence in self._active_sequences.values():
            if sequence.priority < top_prio:
                break
            top_prio = sequence.priority
            ret.append(sequence)
        return ret

    @callback
    def _get_sequence_step_events(self) -> set:
        return {
            anim.wait()
            for anim in self._running_sequences.values()
            if anim and anim.is_running()
        }

    async def _wake_loop(self, log_trigger: str | None = None) -> None:
        """Wake the event loop to process light sequences."""
        await self._task_queue.put(_WakeCommand(log_trigger=log_trigger))

    async def _reset_running_sequences(self) -> None:
        """Immediately stop all running sequences and reset last-set color."""
        while self._running_sequences:
            _seq_id, anim = self._running_sequences.popitem()
            await anim.stop()
        self._last_set_color = None
        await self._wake_loop()

    @callback
    def _friendly_name(self, entity_id: str) -> str:
        """Return the friendly name of an entity, falling back to entity_id."""
        state = self._get_hass().states.get(entity_id)
        if state:
            return state.attributes.get("friendly_name") or entity_id
        return entity_id

    def _log_display_state(
        self,
        top_sequences: list[ActiveNotification],
        log_trigger: str | None = None,
    ) -> None:
        """Log a notification event combined with what is currently displaying."""
        if self._event_logger is None or log_trigger is None:
            return

        top_ids = frozenset(s.notify_id for s in top_sequences)

        if STATE_OFF in top_ids or None in top_ids:
            displaying = "Off"
        elif STATE_ON in top_ids:
            displaying = "Light On"
        else:
            is_peek = any(s.priority > MAXIMUM_PRIORITY for s in top_sequences)
            names = ", ".join(
                self._friendly_name(s.notify_id)
                for s in top_sequences
                if s.notify_id not in (None, STATE_OFF, STATE_ON)
            )
            if is_peek:
                displaying = f"{names} (peeking)"
            else:
                displaying = f"{names} (pri {top_sequences[0].priority})"

        self._event_logger.update_message(f"{log_trigger}, displaying {displaying}")

    # ------------------------------------------------------------------
    # Process sequence list
    # ------------------------------------------------------------------

    async def _process_sequence_list(self, log_trigger: str | None = None) -> None:
        """Pick the top-priority sequence(s) and drive the wrapped light."""
        hass = self._get_hass()
        top_sequences = self._get_top_sequences()
        if not top_sequences:
            _LOGGER.error("Sequence list empty for %s", self._entity_name)
            return

        top_sequence = top_sequences[0]
        top_priority = top_sequence.priority

        self._log_display_state(top_sequences, log_trigger)

        wrapped_state = hass.states.get(self._wrapped_entity_id)
        bulb_is_off = wrapped_state is None or wrapped_state.state != STATE_ON
        warmup_ms: int = (
            self._config_entry.data.get(CONF_WARMUP_TIME, 0) if bulb_is_off else 0
        )

        # Start any top-priority sequences not yet running.
        for sequence in top_sequences:
            if (
                sequence.notify_id is not None
                and sequence.notify_id not in self._running_sequences
            ):
                sequence.set_initial_hold(warmup_ms / 1000.0)
                on_complete: Callable[[], None] | None = None
                if sequence.notify_id and sequence.clear_delay == 0:
                    nid = sequence.notify_id

                    def _make_autoclear(entity_id: str) -> Callable[[], None]:
                        def _fire() -> None:
                            hass.async_create_task(
                                hass.services.async_call(
                                    Platform.SWITCH,
                                    SERVICE_TURN_OFF,
                                    service_data={ATTR_ENTITY_ID: entity_id},
                                )
                            )

                        return _fire

                    on_complete = _make_autoclear(nid)
                await sequence.run(hass, self._config_entry, on_complete)
                self._running_sequences[sequence.notify_id] = sequence

        # Stop sequences that are lower priority than the current top.
        remove_list = {
            notify_id: anim
            for notify_id, anim in self._running_sequences.items()
            if notify_id not in self._active_sequences
            or (anim is not None and anim.priority < top_priority)
        }
        for seq_id, anim in remove_list.items():
            if anim:
                await anim.stop()
            self._running_sequences.pop(seq_id)

        color = top_sequence.color
        if color != self._last_set_color:
            if await self._on_color_change(**color.light_params):
                self._last_set_color = color
            else:
                _LOGGER.error(
                    "%s failed to set wrapped light, real state unknown",
                    self._entity_name,
                )
                await asyncio.sleep(INIT_STATE_UPDATE_DELAY_SEC)
                await self._reset_running_sequences()

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    async def _worker_func(self) -> None:
        """Try/except wrapper around the inner work loop."""
        while True:
            try:
                await self._work_loop()
            except asyncio.CancelledError:
                break
            except Exception:
                _LOGGER.exception("Error running %s worker!", self._entity_name)

    async def _work_loop(self) -> None:
        """Inner loop: drain the queue and keep the light up to date."""
        hass = self._get_hass()
        entry_data = self._config_entry.data
        q_task: asyncio.Task | None = None
        cycle_canceler: Callable | None = None
        cycle_delay_time = entry_data.get(CONF_DELAY_TIME)
        cycle_delay_enabled = entry_data.get(CONF_DELAY, False)
        cycle_delay: timedelta | None = (
            timedelta(**cycle_delay_time)
            if cycle_delay_time is not None and cycle_delay_enabled
            else None
        )
        peek_duration_time = entry_data.get(CONF_PEEK_TIME)
        peek_duration: int = (
            timedelta(**peek_duration_time).seconds
            if peek_duration_time is not None
            else 0
        )

        pending_trigger: str | None = None
        while True:
            await self._process_sequence_list(log_trigger=pending_trigger)
            pending_trigger = None

            # Schedule cycling through same-priority notifications.
            if (
                cycle_delay
                and cycle_canceler is None
                and len(self._running_sequences) > 1
            ):

                async def queue_cycle(_: Any) -> None:
                    nonlocal cycle_canceler
                    cycle_canceler = None
                    if len(self._running_sequences) > 1:
                        await self._task_queue.put(_CycleSameCommand())

                cycle_canceler = async_call_later(hass, cycle_delay, queue_cycle)

            # Wait for either a queue command or an animation step completion.
            if q_task is None or q_task.done():
                q_task = asyncio.create_task(self._task_queue.get())
            wait_tasks = [
                asyncio.create_task(x) for x in self._get_sequence_step_events()
            ]
            wait_tasks.append(q_task)
            done, _pending = await asyncio.wait(
                wait_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            # Cancel step-event tasks that lost the race to avoid task leaks.
            for _t in _pending:
                if _t is not q_task:
                    _t.cancel()
            if q_task in done:
                cmd: _QueueCommand = await q_task
                _LOGGER.info("[%s] Got queue item: [%s]", self._config_entry.title, cmd)
                match cmd:
                    case _DeleteCommand(notify_id=nid):
                        if nid in self._active_sequences:
                            anim = self._active_sequences.pop(nid)
                            if nid in self._running_sequences:
                                await anim.stop()
                                self._running_sequences.pop(nid)

                    case _AddCommand(notify_id=nid, notification=notif):
                        if nid in self._active_sequences:
                            _LOGGER.warning("%s already in active list", nid)
                            # Stop the stale running animation so the new one starts.
                            if nid in self._running_sequences:
                                await self._running_sequences.pop(nid).stop()

                        current_top_priority = next(
                            iter(self._active_sequences.values())
                        ).priority
                        if (
                            peek_duration > 0
                            and notif.peek_enabled
                            and nid != STATE_OFF
                            and notif.priority <= current_top_priority
                        ):
                            auto_clears = (
                                notif.clear_delay == 0 and not notif.loops_forever
                            )
                            original_priority = notif.priority
                            notif.priority += MAXIMUM_PRIORITY
                            _LOGGER.debug(
                                "Boosting %s priority to %d for %f seconds",
                                nid,
                                notif.priority,
                                peek_duration,
                            )
                            if not auto_clears:

                                async def restore_priority(
                                    _: Any,
                                    priority: int = original_priority,
                                    notify_id: str = nid,
                                ) -> None:
                                    sequence = self._active_sequences.get(notify_id)
                                    if sequence is not None:
                                        sequence.priority = priority
                                        _LOGGER.debug(
                                            "Restoring %s priority to %d",
                                            notify_id,
                                            sequence.priority,
                                        )
                                        self._sort_active_sequences()
                                        trigger = (
                                            f"{self._friendly_name(notify_id)}"
                                            f" (pri {priority}) peek expired"
                                        )
                                        await self._wake_loop(log_trigger=trigger)

                                async_call_later(hass, peek_duration, restore_priority)

                        self._active_sequences[nid] = notif
                        self._sort_active_sequences()

                    case _CycleSameCommand():
                        if self._active_sequences:
                            it = iter(self._active_sequences.items())
                            new_dict: dict[str, ActiveNotification] = {}
                            top_id, top_seq = next(it)
                            if top_id != STATE_OFF:
                                top_prio = top_seq.priority
                                inserted_top = False
                                for it_id, it_seq in it:
                                    # Insert the demoted top entry just before
                                    # the first lower-priority peer.
                                    if top_prio > it_seq.priority and not inserted_top:
                                        new_dict[top_id] = top_seq
                                        inserted_top = True
                                    new_dict[it_id] = it_seq
                                # All peers share the same priority — append to end.
                                if not inserted_top:
                                    new_dict[top_id] = top_seq
                                self._active_sequences = new_dict

                    case _WakeCommand():
                        pass  # log_trigger handled below

                if cmd.log_trigger is not None:
                    pending_trigger = cmd.log_trigger
                self._task_queue.task_done()
