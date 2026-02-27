"""Stub for homeassistant.util.color — upstream light.py imports these.

Upstream code (not ours) calls color_temperature_to_rgb for kelvin-to-RGB
conversion. This stub lets tests import light.py without a full HA install.

Algorithm sourced from HA core:
https://github.com/home-assistant/core/blob/dev/homeassistant/util/color.py
"""

import math


def color_temperature_to_rgb(
    color_temperature_kelvin: float,
) -> tuple[float, float, float]:
    """Convert color temperature (Kelvin) to RGB.

    Matches HA's implementation. Input clamped to [1000, 40000]K.
    See: https://github.com/home-assistant/core/blob/dev/homeassistant/util/color.py
    """
    color_temperature_kelvin = max(1000, min(40000, color_temperature_kelvin))
    tmp_internal = color_temperature_kelvin / 100.0

    # Red
    if tmp_internal <= 66:
        red = 255.0
    else:
        tmp_red = 329.698727446 * ((tmp_internal - 60) ** -0.1332047592)
        red = max(0.0, min(255.0, tmp_red))

    # Green
    if tmp_internal <= 66:
        tmp_green = 99.4708025861 * math.log(tmp_internal) - 161.1195681661
        green = max(0.0, min(255.0, tmp_green))
    else:
        tmp_green = 288.1221695283 * ((tmp_internal - 60) ** -0.0755148492)
        green = max(0.0, min(255.0, tmp_green))

    # Blue
    if tmp_internal >= 66:
        blue = 255.0
    elif tmp_internal <= 19:
        blue = 0.0
    else:
        tmp_blue = 138.5177312231 * math.log(tmp_internal - 10) - 305.0447927307
        blue = max(0.0, min(255.0, tmp_blue))

    return (red, green, blue)
