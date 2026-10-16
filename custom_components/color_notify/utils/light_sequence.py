"""Light sequence animation utils."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from copy import copy
from dataclasses import dataclass, field, replace
import json
import logging
import math
from typing import Any

from homeassistant.components.light import ATTR_RGB_COLOR, ATTR_TRANSITION
from homeassistant.const import CONF_DELAY, CONF_RGB

from ..const import OFF_RGB, WARM_WHITE_RGB

_LOGGER = logging.getLogger(__name__)


def _interpolate(start: tuple, end: tuple, amount: float) -> tuple:
    return tuple(
        int(t1 + (t2 - t1) * amount) for t1, t2 in zip(start, end, strict=True)
    )


@dataclass
class ColorInfo:
    """Internal color representation."""

    rgb: tuple = WARM_WHITE_RGB
    brightness: float = 100.0
    transition: float | None = None

    def interpolated_to(self, end: ColorInfo, amount: float) -> ColorInfo:
        """Return a new ColorInfo that is 0-1.0 linearly interpolated between end."""
        a = (*self.rgb, self.brightness)
        b = (*end.rgb, end.brightness)
        return ColorInfo(*_interpolate(a, b, amount))

    @property
    def light_params(self) -> dict[str, Any]:
        """Return dict suitable for passing to light.turn_on service."""
        params: dict[str, Any] = {ATTR_RGB_COLOR: self.rgb}

        if self.transition is not None:
            params[ATTR_TRANSITION] = self.transition

        return params


class LightSequence:
    """Handle cycling through sequences of colors."""

    def __init__(self) -> None:
        """Initialize a new LightSequence."""
        self._steps: list[_SeqStep] = []
        self._workspace: _SeqWorkspace = _SeqWorkspace()
        self._loops_forever: bool = False

    async def runNextStep(self) -> bool:
        """Run the next step, returning 'True' if done."""
        if self._workspace.next_idx >= len(self._steps):
            return True
        next_step = self._steps[self._workspace.next_idx]
        self._workspace.next_idx += 1
        await next_step.execute(self._workspace)
        return self._workspace.next_idx >= len(self._steps)

    def _addStep(self, step: _SeqStep) -> None:
        """Add a new step to this LightSequence."""
        step.idx = len(self._steps)
        self._steps.append(step)

    @staticmethod
    def create_from_pattern(pattern: list[str | ColorInfo]) -> LightSequence:
        """Create a LightSequence from a supplied pattern."""
        new_sequence: LightSequence = LightSequence()
        initial_color: ColorInfo | None = None
        next_loop_id: int = 1
        loop_stack: list[int] = []
        for idx, item in enumerate(pattern):
            if isinstance(item, ColorInfo):
                if initial_color is None:
                    initial_color = item
                new_sequence._addStep(_StepSetColor(item))
            elif isinstance(item, str):
                item = item.strip()
                if item == "[":
                    new_sequence._addStep(_StepOpenLoop(next_loop_id))
                    loop_stack.append(next_loop_id)
                    next_loop_id += 1
                elif item.startswith("]"):
                    # ']' loops forever; '], N' repeats the loop body N more times.
                    rest = item[1:].strip()
                    if not rest:
                        iter_cnt = -1
                        new_sequence._loops_forever = True
                    else:
                        count_txt = rest.removeprefix(",").strip()
                        if not rest.startswith(",") or not count_txt.isdecimal():
                            raise Exception(
                                f"Error in entry #{idx+1}: loop count must be a"
                                f" non-negative integer (e.g. '], 2'), got '{item}'"
                            )
                        iter_cnt = int(count_txt)

                    if len(loop_stack) == 0:
                        raise Exception(
                            f"Loop close in entry #{idx+1} with no open loop!"
                        )
                    loop_id = loop_stack.pop()
                    new_sequence._addStep(_StepCloseLoop(loop_id, iter_cnt))
                else:
                    try:
                        json_txt = f"{{{item.strip().strip('{}')}}}"  # Strip and re-add curly braces
                        item_dict = json.loads(json_txt)
                        # Accept either 'rgb_color' or 'rgb'. Only fall back to 'rgb'
                        # when 'rgb_color' is absent, so 'rgb' isn't required.
                        if ATTR_RGB_COLOR in item_dict:
                            rgb = item_dict[ATTR_RGB_COLOR]
                        elif CONF_RGB in item_dict:
                            rgb = item_dict[CONF_RGB]
                        else:
                            raise ValueError(
                                f"missing color: provide '{ATTR_RGB_COLOR}' or '{CONF_RGB}'"
                            )
                        # Same shape HA's rgb_color accepts: 3 numbers, 0-255.
                        if (
                            not isinstance(rgb, list)
                            or len(rgb) != 3
                            or any(
                                isinstance(c, bool)
                                or not isinstance(c, (int, float))
                                or not 0 <= c <= 255
                                for c in rgb
                            )
                        ):
                            raise ValueError(
                                "color must be 3 numbers from 0 to 255"
                                f" (e.g. [255, 0, 0]), got {rgb!r}"
                            )
                        # JSON yields lists; store a tuple so it compares equal to
                        # tuple constants such as OFF_RGB.
                        rgb = tuple(rgb)

                        raw_transition = item_dict.get(ATTR_TRANSITION)

                        if raw_transition is None:
                            transition = None
                        elif (
                            isinstance(raw_transition, bool)
                            or not isinstance(raw_transition, (int, float))
                            or not math.isfinite(raw_transition)
                            or raw_transition < 0
                        ):
                            raise ValueError(
                                "'transition' must be a finite, non-negative number"
                            )
                        else:
                            transition = float(raw_transition)

                    except Exception as e:
                        raise Exception(f"Error in entry #{idx+1}: {str(e)}")
                    color = ColorInfo(rgb=rgb, transition=transition)
                    if initial_color is None:
                        initial_color = color
                    new_sequence._addStep(_StepSetColor(color))
                    if delay := item_dict.get(CONF_DELAY):
                        new_sequence._addStep(_StepDelay(delay))
        new_sequence._workspace.color = initial_color or ColorInfo(OFF_RGB, 0)
        if len(loop_stack) > 0:
            raise Exception(
                f"The loop opened at entry #{loop_stack[0]} was not closed!"
            )
        return new_sequence

    @property
    def loops_forever(self) -> bool:
        """Return True if this sequence loops forever."""
        return self._loops_forever

    @property
    def color(self) -> ColorInfo:
        """Return this sequence's current color."""
        return copy(self._workspace.color)

    @color.setter
    def color(self, value: ColorInfo) -> None:
        """Override this sequence's current color."""
        self._workspace.color = value


@dataclass
class _LoopInfo:
    """Information to store per-loop in a sequence."""

    open_idx: int = 0
    loop_cnt: int = 0


@dataclass
class _SeqWorkspace:
    """Runtime information for a sequence."""

    next_idx: int = 0
    cur_loop: int = 0
    data: dict[Any, Any] = field(default_factory=dict)
    color: ColorInfo = field(default_factory=ColorInfo)


class _SeqStep(ABC):
    """Abstract class representing a step in a sequence."""

    def __init__(self) -> None:
        self._idx: int | None = None  # This step's index within the sequence

    @abstractmethod
    async def execute(self, workspace: _SeqWorkspace):
        """Perform this steps action to update the workspace."""

    @property
    def idx(self):
        return self._idx

    @idx.setter
    def idx(self, value):
        self._idx = value


class _StepOpenLoop(_SeqStep):
    """Sequence step that opens a loop."""

    def __init__(self, loop_id: int) -> None:
        super().__init__()
        self._loop_id = loop_id

    async def execute(self, workspace: _SeqWorkspace):
        assert self.idx is not None
        if self._loop_id not in workspace.data:
            workspace.data[self._loop_id] = _LoopInfo(open_idx=self.idx)


class _StepCloseLoop(_SeqStep):
    """Sequence step that closes a loop."""

    def __init__(self, loop_id: int, loop_cnt: int) -> None:
        super().__init__()
        self._loop_id = loop_id
        self._total_repeats = loop_cnt

    async def execute(self, workspace: _SeqWorkspace):
        info: _LoopInfo | None = workspace.data.get(self._loop_id)
        if info is None:
            raise ValueError("CloseLoop with no matching OpenLoop!")
        info.loop_cnt += 1
        if self._total_repeats < 0 or info.loop_cnt <= self._total_repeats:
            workspace.next_idx = info.open_idx
        else:
            workspace.data.pop(self._loop_id)


class _StepSetColor(_SeqStep):
    """Sequence step that updates the color."""

    def __init__(self, color: ColorInfo) -> None:
        super().__init__()
        self._color: ColorInfo = color

    async def execute(self, workspace: _SeqWorkspace):
        workspace.color = replace(self._color)  # creates a copy


class _StepDelay(_SeqStep):
    """Sequence step that waits."""

    def __init__(self, delay: float) -> None:
        super().__init__()
        self._delay = delay

    async def execute(self, workspace: _SeqWorkspace):
        await asyncio.sleep(self._delay)
