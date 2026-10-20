"""HTTP views serving the SVG previews shown on the notification overview."""

from __future__ import annotations

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import COLOR_WHEEL_URL, DOMAIN, PATTERN_SWATCH_URL
from .utils.swatch import decode_colors, decode_pattern, error_svg, pattern_svg, wheel_svg

# Output depends only on the URL, so browsers may cache it freely.
_HEADERS = {"Cache-Control": "public, max-age=86400"}


def _svg_response(svg: str) -> web.Response:
    return web.Response(text=svg, content_type="image/svg+xml", headers=_HEADERS)


class PatternSwatchView(HomeAssistantView):
    """Render the pattern given in the URL.

    No auth: <img> tags can't send HA's bearer token, and this only draws the
    caller's own (size-limited) input, so it exposes nothing.
    """

    url = PATTERN_SWATCH_URL
    name = f"api:{DOMAIN}:pattern"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        try:
            return _svg_response(pattern_svg(decode_pattern(request.query.get("p", ""))))
        except Exception:
            return _svg_response(error_svg())


class ColorWheelView(HomeAssistantView):
    """Render the colors-in-use wheel for the colors given in the URL."""

    url = COLOR_WHEEL_URL
    name = f"api:{DOMAIN}:wheel"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        try:
            colors = decode_colors(request.query.get("c", ""))
        except Exception:
            return web.Response(status=400)
        return _svg_response(wheel_svg(colors))
