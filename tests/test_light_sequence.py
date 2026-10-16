"""Tests for LightSequence pattern parsing and playback."""

import pytest

from custom_components.color_notify.const import OFF_RGB
from custom_components.color_notify.utils.light_sequence import (
    ColorInfo,
    LightSequence,
    _StepSetColor,
)


def _set_color_steps(seq: LightSequence) -> list[ColorInfo]:
    return [step._color for step in seq._steps if isinstance(step, _StepSetColor)]


async def _count_colors_played(seq: LightSequence) -> int:
    """Run a finite sequence to completion and count the color steps executed."""
    played = 0
    while True:
        next_step = seq._steps[seq._workspace.next_idx]
        if isinstance(next_step, _StepSetColor):
            played += 1
        if await seq.runNextStep():
            return played


class TestTransitionParsing:
    def test_transition_is_parsed_and_passed_to_light(self) -> None:
        """A 'transition' value ends up in the light.turn_on params."""
        seq = LightSequence.create_from_pattern(
            ['{"rgb": [255, 0, 0], "transition": 0.5}']
        )
        [color] = _set_color_steps(seq)
        assert color.transition == 0.5
        assert color.light_params == {"rgb_color": (255, 0, 0), "transition": 0.5}

    def test_integer_transition_is_stored_as_float(self) -> None:
        seq = LightSequence.create_from_pattern(['{"rgb": [255, 0, 0], "transition": 2}'])
        [color] = _set_color_steps(seq)
        assert color.transition == 2.0
        assert isinstance(color.transition, float)

    def test_no_transition_leaves_params_unchanged(self) -> None:
        """Patterns without 'transition' send the same params as before transitions existed."""
        seq = LightSequence.create_from_pattern(['{"rgb": [0, 0, 255], "delay": 1}'])
        [color] = _set_color_steps(seq)
        assert color.transition is None
        assert color.light_params == {"rgb_color": (0, 0, 255)}

    @pytest.mark.parametrize("bad_value", ['"slow"', "true", "-1", "[1]"])
    def test_invalid_transition_is_rejected(self, bad_value: str) -> None:
        with pytest.raises(Exception, match="Error in entry #1: 'transition' must be"):
            LightSequence.create_from_pattern(
                ['{"rgb": [255, 0, 0], "transition": %s}' % bad_value]
            )


class TestRgbKeys:
    def test_rgb_color_key_alone_is_accepted(self) -> None:
        """'rgb_color' works without also supplying 'rgb'."""
        seq = LightSequence.create_from_pattern(['{"rgb_color": [1, 2, 3]}'])
        [color] = _set_color_steps(seq)
        assert color.rgb == (1, 2, 3)

    def test_rgb_color_takes_precedence_over_rgb(self) -> None:
        seq = LightSequence.create_from_pattern(
            ['{"rgb_color": [1, 2, 3], "rgb": [4, 5, 6]}']
        )
        [color] = _set_color_steps(seq)
        assert color.rgb == (1, 2, 3)

    def test_missing_color_is_rejected(self) -> None:
        with pytest.raises(
            Exception, match="Error in entry #1: missing color: provide 'rgb_color' or 'rgb'"
        ):
            LightSequence.create_from_pattern(['{"delay": 1}'])

    @pytest.mark.parametrize(
        "rgb", ['"red"', "[255, 0]", "[255, 0, 0, 0]", "[256, 0, 0]", "[-1, 0, 0]", "[true, 0, 0]"]
    )
    def test_bad_color_is_rejected(self, rgb: str) -> None:
        with pytest.raises(Exception, match="Error in entry #1: color must be 3 numbers"):
            LightSequence.create_from_pattern(['{"rgb": %s}' % rgb])

    def test_float_color_is_accepted(self) -> None:
        """HA's rgb_color coerces floats, so saved patterns using them keep working."""
        seq = LightSequence.create_from_pattern(['{"rgb": [255.0, 0, 0]}'])
        [color] = _set_color_steps(seq)
        assert color.rgb == (255.0, 0, 0)

    def test_json_rgb_is_stored_as_tuple(self) -> None:
        """JSON lists become tuples so a black step compares equal to OFF_RGB."""
        seq = LightSequence.create_from_pattern(['{"rgb": [0, 0, 0], "transition": 2}'])
        [color] = _set_color_steps(seq)
        assert color.rgb == OFF_RGB


class TestLoopCounts:
    @pytest.mark.parametrize(("close", "expected_plays"), [("],0", 1), ("], 1", 2), ("],5", 6)])
    async def test_loop_count_is_number_of_extra_repeats(
        self, close: str, expected_plays: int
    ) -> None:
        """'], N' plays the loop body N more times (N + 1 total), as the README documents."""
        seq = LightSequence.create_from_pattern(["[", '{"rgb": [255, 0, 0]}', close])
        assert not seq.loops_forever
        assert await _count_colors_played(seq) == expected_plays

    def test_bare_close_loops_forever(self) -> None:
        seq = LightSequence.create_from_pattern(["[", '{"rgb": [255, 0, 0]}', "]"])
        assert seq.loops_forever

    @pytest.mark.parametrize("close", ["], -1", "], 2, 3", "], abc", "],", "] 2", "]x"])
    def test_malformed_loop_count_is_rejected(self, close: str) -> None:
        with pytest.raises(Exception, match="Error in entry #3: loop count must be"):
            LightSequence.create_from_pattern(["[", '{"rgb": [255, 0, 0]}', close])
