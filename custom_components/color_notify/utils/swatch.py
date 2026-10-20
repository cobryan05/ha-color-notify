"""SVG previews of notification colors and patterns for the overview page."""

from __future__ import annotations

import base64
import colorsys
import json
import math
from collections.abc import Iterable
from typing import Any

from homeassistant.const import CONF_NAME

from ..const import (
    COLOR_WHEEL_URL,
    CONF_NOTIFY_PATTERN,
    CONF_PRIORITY,
    CONF_RGB_SELECTOR,
    DEFAULT_PRIORITY,
    OFF_RGB,
    PATTERN_SWATCH_URL,
    WARM_WHITE_RGB,
)
from .light_sequence import ColorInfo, LightSequence

MAX_PATTERN_ITEMS = 64
MAX_ENCODED_LEN = 4096
MAX_WHEEL_COLORS = 256

_DOT = 24  # animated dot diameter
_STRIP_X = 32  # strip starts after the dot
_STRIP_W = 160  # width shared by the timed blocks
_HOLD_W = 24  # final color, held until the notification clears
_MIN_W = 6  # so instant (zero-delay) steps are still visible
_H = 24
_OUTLINE = "#8a8a8a"  # visible on both light and dark dialogs, and around black


def encode_pattern(pattern: list[str]) -> str:
    """Encode a pattern for the swatch URL."""
    return base64.urlsafe_b64encode(json.dumps(pattern).encode()).decode().rstrip("=")


def decode_pattern(encoded: str) -> list[str]:
    """Decode a swatch URL pattern, rejecting anything oversized or malformed."""
    if len(encoded) > MAX_ENCODED_LEN:
        raise ValueError("pattern too long")
    pattern = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    if (
        not isinstance(pattern, list)
        or len(pattern) > MAX_PATTERN_ITEMS
        or not all(isinstance(item, str) for item in pattern)
    ):
        raise ValueError("pattern must be a short list of strings")
    return pattern


def solid_pattern(rgb: Any) -> list[str]:
    """Pattern text for a notification that only has a solid color."""
    return [json.dumps({"rgb": [int(c) for c in rgb]})]


def pattern_colors(pattern: list[str]) -> list[tuple[int, int, int]]:
    """Return the distinct colors a pattern shows, in first-seen order."""
    timeline = LightSequence.create_from_pattern(pattern, strict=False).preview_timeline()
    seen: dict[tuple, None] = {}
    for color, _ in timeline.colors:
        seen.setdefault(_rgb(color), None)
    return list(seen)


def _rgb(color: ColorInfo) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(c))) for c in color.rgb)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _svg(width: int, height: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
        f' viewBox="0 0 {width} {height}">{body}</svg>'
    )


def error_svg() -> str:
    """Swatch shown for a pattern that can't be parsed."""
    r = _DOT // 2
    return _svg(
        _DOT,
        _H,
        f'<circle cx="{r}" cy="{r}" r="{r - 1}" fill="none" stroke="{_OUTLINE}"/>'
        f'<path d="M7 7L17 17M17 7L7 17" stroke="#d33" stroke-width="2.5"/>',
    )


def pattern_svg(pattern: list[str]) -> str:
    """Animated dot that plays the pattern, plus a strip of its steps (width ~ time)."""
    timeline = LightSequence.create_from_pattern(pattern, strict=False).preview_timeline()
    steps = [(_rgb(color), seconds, color.transition or 0.0) for color, seconds in timeline.colors]
    if not steps:
        steps = [(OFF_RGB, 0.0, 0.0)]

    total = sum(seconds for _, seconds, _ in steps)
    timed = steps[:-1] if not timeline.loops_forever else steps
    timed_total = sum(seconds for _, seconds, _ in timed)
    defs: list[str] = []
    blocks: list[str] = []
    x = float(_STRIP_X)
    prev = steps[-1][0] if timeline.loops_forever else OFF_RGB
    for i, (rgb, seconds, transition) in enumerate(steps):
        last_hold = i == len(steps) - 1 and not timeline.loops_forever
        if last_hold:
            width = float(_HOLD_W)
        elif timed_total > 0:
            width = max(float(_MIN_W), _STRIP_W * seconds / timed_total)
        else:
            width = float(_STRIP_W) / max(1, len(timed))
        fill = _hex(rgb)
        if transition > 0 and i > 0:
            # Fade from the previous color over the transition's share of the block.
            share = 1.0 if seconds <= 0 else min(1.0, transition / seconds)
            defs.append(
                f'<linearGradient id="g{i}"><stop offset="0" stop-color="{_hex(prev)}"/>'
                f'<stop offset="{share:.3f}" stop-color="{fill}"/></linearGradient>'
            )
            fill = f"url(#g{i})"
        blocks.append(
            f'<rect x="{x:.1f}" y="4" width="{width:.1f}" height="{_H - 8}" fill="{fill}"/>'
        )
        x += width
        prev = rgb

    strip_end = x
    blocks.append(
        f'<rect x="{_STRIP_X}" y="4" width="{strip_end - _STRIP_X:.1f}" height="{_H - 8}"'
        f' fill="none" stroke="{_OUTLINE}"/>'
    )
    marker = "↻" if timeline.loops_forever else ("…" if timeline.truncated else "")
    if marker:
        blocks.append(
            f'<text x="{strip_end + 4:.1f}" y="17" font-size="15" fill="{_OUTLINE}"'
            f' font-family="sans-serif">{marker}</text>'
        )

    r = _DOT // 2
    dot = f'<circle cx="{r}" cy="{r}" r="{r - 1}" fill="{_hex(steps[0][0])}" stroke="{_OUTLINE}">'
    if total > 0:
        dot += _dot_animation(steps, total, timeline.loops_forever)
    dot += "</circle>"

    width = math.ceil(strip_end) + (20 if marker else 2)
    return _svg(width, _H, f"<defs>{''.join(defs)}</defs>{dot}{''.join(blocks)}")


def _dot_animation(steps: list[tuple], total: float, loops: bool) -> str:
    """SMIL fill animation that plays the steps at real speed, then repeats."""
    hold = 0.0 if loops else 1.5  # show the final color for a moment before replaying
    cycle = total + hold
    times: list[float] = []
    values: list[str] = []
    t = 0.0
    prev = steps[-1][0] if loops else steps[0][0]
    for i, (rgb, seconds, transition) in enumerate(steps):
        # The final color of a finite pattern can keep fading into the hold.
        available = seconds + (hold if i == len(steps) - 1 else 0.0)
        fade = min(transition, available) if transition > 0 else 0.0
        times += [t, t + fade]
        values += [_hex(prev), _hex(rgb)]
        t += seconds
        prev = rgb
    times.append(cycle)
    values.append(_hex(prev))
    key_times = ";".join(f"{min(1.0, tt / cycle):.4f}" for tt in times)
    return (
        f'<animate attributeName="fill" dur="{cycle:.3f}s" repeatCount="indefinite"'
        f' calcMode="linear" keyTimes="{key_times}" values="{";".join(values)}"/>'
    )


def wheel_svg(colors: list[tuple[int, int, int]], size: int = 180) -> str:
    """Hue/saturation disk with a dot for each color in use.

    Angle is hue and distance from the center is saturation, so unused hues
    show up as empty sectors. Brightness is ignored; black (off) isn't drawn.
    """
    c = size / 2
    radius = c - 8
    wedges = []
    for deg in range(0, 360, 5):
        a0, a1 = math.radians(deg - 90), math.radians(deg + 5.5 - 90)
        r, g, b = colorsys.hsv_to_rgb(deg / 360, 1, 1)
        wedges.append(
            f'<path d="M{c},{c} L{c + radius * math.cos(a0):.2f},{c + radius * math.sin(a0):.2f}'
            f' A{radius},{radius} 0 0 1 {c + radius * math.cos(a1):.2f},{c + radius * math.sin(a1):.2f} Z"'
            f' fill="{_hex((round(r * 255), round(g * 255), round(b * 255)))}"/>'
        )
    body = [
        '<defs><radialGradient id="w"><stop offset="0" stop-color="#fff"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient></defs>',
        f'<g opacity="0.45">{"".join(wedges)}'
        f'<circle cx="{c}" cy="{c}" r="{radius}" fill="url(#w)"/></g>',
        f'<circle cx="{c}" cy="{c}" r="{radius}" fill="none" stroke="{_OUTLINE}"/>',
    ]
    for rgb in colors[:MAX_WHEEL_COLORS]:
        if rgb == OFF_RGB:
            continue
        h, s, _ = colorsys.rgb_to_hsv(*(v / 255 for v in rgb))
        angle = math.radians(h * 360 - 90)
        x, y = c + radius * s * math.cos(angle), c + radius * s * math.sin(angle)
        body.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{_hex(rgb)}"'
            ' stroke="#000" stroke-width="2"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8.5" fill="none" stroke="#fff"/>'
        )
    return _svg(size, size, "".join(body))


def encode_colors(colors: list[tuple[int, int, int]]) -> str:
    """Encode colors for the wheel URL as comma-separated hex."""
    return ",".join(_hex(rgb)[1:] for rgb in colors[:MAX_WHEEL_COLORS])


def decode_colors(encoded: str) -> list[tuple[int, int, int]]:
    """Decode wheel URL colors, rejecting anything oversized or malformed."""
    parts = [p for p in encoded.split(",") if p] if encoded else []
    if len(parts) > MAX_WHEEL_COLORS or any(len(p) != 6 for p in parts):
        raise ValueError("bad colors")
    return [tuple(int(p[i : i + 2], 16) for i in (0, 2, 4)) for p in parts]


def _md_cell(text: Any) -> str:
    """Escape text so it can't break out of a table cell or an image's alt text."""
    out = str(text).replace("\\", "\\\\").replace("\n", " ")
    for ch in "|[]":
        out = out.replace(ch, "\\" + ch)
    return out


def overview_markdown(notifications: Iterable[dict[str, Any]]) -> str:
    """Colors-in-use wheel plus a table of notifications ({"pool", "data"} dicts, in order)."""
    rows: list[str] = []
    used: dict[tuple, None] = {}
    for item in notifications:
        data = item["data"]
        pattern = data.get(CONF_NOTIFY_PATTERN) or solid_pattern(
            data.get(CONF_RGB_SELECTOR, WARM_WHITE_RGB)
        )
        try:
            used.update(dict.fromkeys(pattern_colors(pattern)))
        except Exception:  # still listed; its swatch shows the error mark
            pass
        name = _md_cell(data.get(CONF_NAME, ""))
        priority = float(data.get(CONF_PRIORITY, DEFAULT_PRIORITY))
        rows.append(
            f"| ![{name}]({PATTERN_SWATCH_URL}?p={encode_pattern(pattern)})"
            f" | {name} | {_md_cell(item['pool'])} | {priority:g} |"
        )
    if not rows:
        return "_No notifications yet. Create one from the pool menu._"

    return "\n".join(
        [
            f"![Colors in use]({COLOR_WHEEL_URL}?c={encode_colors(list(used))})",
            "",
            "_Colors in use: angle is hue, pale colors sit near the center."
            " Empty areas are free._",
            "",
            "| Preview | Name | Pool | Priority |",
            "|---|---|---|---|",
            *rows,
        ]
    )
