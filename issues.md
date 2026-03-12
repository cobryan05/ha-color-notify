# Color Notify Issues

## 2026-02-17: Wrapper Light Restores Stale Bright-White State on HA Startup

### Symptom

Every HA restart blasts living room lights to 100% brightness / ~4800K white. Happens immediately on startup.

### Root Cause

`light.light_living_room_notify` (Color Notify wrapper light wrapping the Hue room group `light.living_room`) restores its cached internal state on HA startup. This sends `light.turn_on` to the underlying wrapped light with:
- `brightness: 255` (100%)
- `rgb_color: [255, 249, 216]` (near-white)
- `color_temp_kelvin: 4787` (exceeds our 3200K max)
- `context: user_id=null, parent_id=null` (internal restore, no user action)

The cached state came from a previous bright white notification that was set and never properly cleared in Color Notify's internal state.

### Evidence

Integration bisect proved Color Notify is the sole cause:

| Config | White Blast? |
|--------|-------------|
| All disabled (Hue + HomeKit + Color Notify) | No |
| Hue only | No |
| Hue + HomeKit | No |
| Hue + HomeKit + Color Notify | **YES** |

### Fix Needed

Options:
1. **Don't restore wrapper light state on startup** — the wrapped real light already has its own state on the Hue bridge. Color Notify should read the current state, not restore a cached one.
2. **Clear notification state on startup** — if no active notifications, the wrapper should be transparent (pass through real light state).
3. **Only restore if there are active notifications** — check if any notification switches are ON before restoring.

### Fix Applied

Added `restore_power` config option (default: `False`). When false, startup only restores internal tracking state (`_attr_is_on`) without sending `turn_on`/`turn_off` to the wrapped real light. When true, preserves old behavior for users who want it.

**Files changed** (on `main` branch):
- `const.py` — added `CONF_RESTORE_POWER`
- `light.py` — reads config, conditionally restores
- `config_flow.py` — added to `ADD_LIGHT_DEFAULTS` and `ADD_LIGHT_SCHEMA`
- `translations/en.json` — label for config UI

**Tests**: `tests/test_restore_power.py` — 8 tests covering default false, explicit true/false, restore with ON/OFF state, no previous state.

**Verified**: 2 consecutive HA restarts with fix deployed — no white blast. Color Notify loaded and tracking state correctly.

### Related

- The wrapper wraps `light.living_room` which is a **Hue room group** (banned from automations in our setup). This amplifies the damage since the room group sends commands to 12+ member lights.
- Color Notify was originally intended for non-color rooms and notification purposes only.

---

## Backlog

### Wrapper should not wrap Hue room groups

The `[Light] Living Room Notify` config entry wraps `light.living_room` (Hue room group entity). This is dangerous:
- Hue room groups have unpredictable behavior (active scene layer, unreliable propagation)
- Any Color Notify command goes through the room group to all 12 lights
- Should wrap an HA-managed group (`light.living_room_lights`) or individual lights instead

### color_mode_pref not respected on startup restore

The config has `color_mode_pref: "color_temp"` but the startup restore sent `rgb_color` mode. The preference should be applied during restore too.
