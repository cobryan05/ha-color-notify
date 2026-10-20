"""Tests for the notification overview previews (timeline, SVGs, markdown)."""

import re

import pytest

from custom_components.color_notify.const import COLOR_WHEEL_URL, PATTERN_SWATCH_URL
from custom_components.color_notify.utils.light_sequence import LightSequence
from custom_components.color_notify.utils.swatch import (
    MAX_ENCODED_LEN,
    MAX_PATTERN_ITEMS,
    decode_colors,
    decode_pattern,
    encode_colors,
    encode_pattern,
    overview_markdown,
    pattern_colors,
    pattern_svg,
    solid_pattern,
    wheel_svg,
)

RED = '{"rgb": [255, 0, 0], "delay": 1}'
BLUE = '{"rgb": [0, 0, 255], "delay": 1}'


def _timeline(pattern, **kwargs):
    return LightSequence.create_from_pattern(pattern, strict=False).preview_timeline(**kwargs)


class TestPreviewTimeline:
    def test_finite_loop_is_expanded(self) -> None:
        timeline = _timeline(["[", RED, BLUE, "],2", '{"rgb": [0, 255, 0]}'])
        assert [c.rgb for c, _ in timeline.colors] == [(255, 0, 0), (0, 0, 255)] * 3 + [(0, 255, 0)]
        assert [s for _, s in timeline.colors] == [1.0] * 6 + [0.0]
        assert not timeline.loops_forever and not timeline.truncated

    def test_forever_loop_is_walked_once(self) -> None:
        timeline = _timeline(["[", RED, BLUE, "]", '{"rgb": [0, 255, 0]}'])
        assert [c.rgb for c, _ in timeline.colors] == [(255, 0, 0), (0, 0, 255)]
        assert timeline.loops_forever

    def test_legacy_forever_loop(self) -> None:
        assert _timeline(["[", RED, "], -1"]).loops_forever

    def test_nested_loops(self) -> None:
        timeline = _timeline(["[", "[", RED, "],1", BLUE, "],1"])
        assert [c.rgb[0] for c, _ in timeline.colors] == [255, 255, 0, 255, 255, 0]

    def test_long_pattern_is_truncated(self) -> None:
        timeline = _timeline(["[", RED, "],100"], max_colors=5)
        assert len(timeline.colors) == 5 and timeline.truncated

    def test_does_not_disturb_playback(self) -> None:
        seq = LightSequence.create_from_pattern(["[", RED, BLUE, "],1"])
        seq.preview_timeline()
        assert seq._workspace.next_idx == 0 and not seq._workspace.data


class TestEncoding:
    def test_pattern_round_trip(self) -> None:
        pattern = ["[", RED, "],2"]
        assert decode_pattern(encode_pattern(pattern)) == pattern

    @pytest.mark.parametrize(
        "bad",
        [
            "x" * (MAX_ENCODED_LEN + 1),
            encode_pattern(["a"] * (MAX_PATTERN_ITEMS + 1)),
            encode_pattern({"not": "a list"}),
            encode_pattern([1, 2]),
            "!!!",
        ],
    )
    def test_bad_pattern_rejected(self, bad: str) -> None:
        with pytest.raises(Exception):
            decode_pattern(bad)

    def test_colors_round_trip(self) -> None:
        colors = [(255, 0, 0), (1, 2, 3)]
        assert decode_colors(encode_colors(colors)) == colors
        assert decode_colors("") == []

    @pytest.mark.parametrize("bad", ["ff00", "zzzzzz", ",".join(["ff0000"] * 300)])
    def test_bad_colors_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError):
            decode_colors(bad)


class TestPatternSvg:
    def test_solid_color_is_static(self) -> None:
        svg = pattern_svg(solid_pattern([255, 140, 0]))
        assert "#ff8c00" in svg and "<animate" not in svg and "↻" not in svg

    def test_forever_loop_animates_and_is_marked(self) -> None:
        svg = pattern_svg(["[", RED, BLUE, "]"])
        assert "↻" in svg
        key_times = [float(t) for t in re.search(r'keyTimes="([^"]+)"', svg).group(1).split(";")]
        assert key_times[0] == 0 and key_times[-1] == 1 and key_times == sorted(key_times)
        values = re.search(r' values="([^"]+)"', svg).group(1).split(";")
        assert len(values) == len(key_times) and {"#ff0000", "#0000ff"} <= set(values)

    def test_transition_draws_gradient(self) -> None:
        svg = pattern_svg([RED, '{"rgb": [0, 0, 255], "delay": 2, "transition": 1}'])
        assert "<linearGradient" in svg and 'offset="0.500"' in svg

    def test_truncated_pattern_is_marked(self) -> None:
        assert "…" in pattern_svg(["[", RED, "],100"])

    def test_wider_block_for_longer_delay(self) -> None:
        svg = pattern_svg(['{"rgb": [255, 0, 0], "delay": 3}', BLUE, "[", RED, "]"])
        widths = [float(w) for w in re.findall(r'<rect x="[^"]+" y="4" width="([^"]+)" height="16" fill="#', svg)]
        assert widths[0] == pytest.approx(3 * widths[1])


class TestWheel:
    def test_dot_per_color_and_black_skipped(self) -> None:
        svg = wheel_svg([(255, 0, 0), (0, 0, 0), (255, 255, 255)])
        assert svg.count('r="7"') == 2
        assert 'fill="#000000" stroke' not in svg

    def test_pattern_colors_are_distinct_in_order(self) -> None:
        assert pattern_colors(["[", RED, BLUE, "],3"]) == [(255, 0, 0), (0, 0, 255)]


class TestOverviewMarkdown:
    def _item(self, name, pool="Home", priority=10, **data):
        return {"pool": pool, "data": {"name": name, "priority": priority, **data}}

    def test_table_rows_and_wheel(self) -> None:
        md = overview_markdown(
            [
                self._item("Alarm", priority=900.0, pattern=["[", RED, BLUE, "]"]),
                self._item("Door", color_picker=[255, 140, 0]),
            ]
        )
        lines = md.splitlines()
        assert lines[0].startswith(f"![Colors in use]({COLOR_WHEEL_URL}?c=")
        assert decode_colors(lines[0].split("?c=")[1].rstrip(")")) == [(255, 0, 0), (0, 0, 255), (255, 140, 0)]
        rows = [l for l in lines if l.startswith(f"| ![")]
        assert rows[0].endswith("| Alarm | Home | 900 |")
        assert rows[1].endswith("| Door | Home | 10 |")
        assert decode_pattern(re.search(r"\?p=([^)]+)\)", rows[1]).group(1)) == solid_pattern([255, 140, 0])
        assert PATTERN_SWATCH_URL in rows[0]

    def test_names_cannot_break_the_table(self) -> None:
        md = overview_markdown([self._item("A|B [x]\nC", pool="P|Q")])
        row = md.splitlines()[-1]
        assert "| A\\|B \\[x\\] C | P\\|Q |" in row
        assert row.count(" | ") == 3  # still exactly four columns

    def test_invalid_pattern_is_still_listed(self) -> None:
        md = overview_markdown([self._item("Broken", pattern=["]"])])
        assert "| Broken |" in md

    def test_empty(self) -> None:
        assert "No notifications yet" in overview_markdown([])
