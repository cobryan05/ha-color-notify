#
[![Color Notify!](https://raw.githubusercontent.com/cobryan05/ha-color-notify/refs/heads/main/images/logo.png?raw=true)](https://github.com/cobryan05/ha-color-notify)

# Color Notify!
### Intelligent, Priority-Based RGB Light Notifications for Home Assistant

**Color Notify** transforms your standard smart lights into dynamic, priority-driven notification displays. By wrapping an existing light entity into a feature-rich virtual wrapper, it seamlessly coordinates complex visual alerts, color patterns, and loops without breaking standard day-to-day lighting controls.

---

## Key Features

* **🎛️ Toggleable Alerts as Switches:** Every notification you create is exposed to Home Assistant as a native `switch` entity. Automating an alert is as simple as flipping a switch.
* **📦 Notification Pools & Subscriptions:** Group notifications into flexible "pools" (e.g., *Security*, *Appliances*). Individual light wrappers can subscribe to an entire pool or specific alerts, allowing a single trigger to sync across multiple rooms.
* **🚦 Intelligent Priority Queueing:** Assign weights to alerts so that critical notifications (like a security alarm) immediately override low-priority status indicators (like a finished laundry cycle).
* **🔄 Seamless Light Control Passthrough:** Your wrapped light still acts as a normal light. Standard on/off, brightness, and color adjustments work right out of the box. Color Notify manages the background states so your regular smart light routines don't break.
* **🎨 Sophisticated Patterns & Animations:** Move beyond boring solid colors. Build complex, looping sequences with custom RGB values, precise delays, and recurring step blocks.

---

## Installation

### Method 1: HACS (Recommended)
*Note: Color Notify is included in the default HACS repositories.*

1. Open **HACS** in your Home Assistant instance.
2. Search for **Color Notify** under the **Integrations** section and download it.
3. Restart Home Assistant.

### Method 2: Manual Installation
1. Download the repository ZIP file.
2. Extract and copy the integration files into your Home Assistant configuration directory under `custom_components/ha-color-notify`.
3. Restart Home Assistant.

### Initial Setup
After restarting, navigate to **Settings > Devices & Services** > **Add Integration**, search for **Color Notify**, and follow the setup prompts.

---

## Configuration

Color Notify operates on two main configuration types: **Lights** (the virtual wrappers) and **Notification Pools** (the collections of alerts).

Once added, you can modify either configuration at any time by clicking the **Configure** button on the integration card.

### 1. Setting up a New Light Wrapper

To enhance a physical light, add a new Color Notify light instance or click **Add Hub** on the integration panel and select an existing light to wrap.

> ⚠️ **Important:** Once wrapped, always interact with the new **Color Notify wrapper light** entity instead of the underlying physical light. Color Notify continuously manages the hardware state; controlling the raw bulb directly will cause conflicting behavior.

[![New Light Setup Example](https://raw.githubusercontent.com/cobryan05/ha-color-notify/refs/heads/main/images/new_light_settings.png?raw=true)](https://raw.githubusercontent.com/cobryan05/ha-color-notify/refs/heads/main/images/new_light_settings.png?raw=true)

#### Light Options
* **Dynamic 'On' Priority:** When enabled, manually turning on the wrapper light temporarily overrides any active notifications by forcing the light state to a priority level just above the active alerts.
* **Auto-cycle Between Same-priority Notifications:** If multiple notifications with identical priorities are active simultaneously, the light will automatically cycle through them based on a customizable delay.
* **Temporary Display of Lower-priority Notifications:** Allows a lower-priority alert to briefly interrupt a higher-priority one when first triggered. Set the duration in seconds (or set to `0` to disable).

---

### 2. Configuring Notifications & Patterns

Notifications are organized into pools and customized with priorities, lifetimes, and behavioral patterns.

[![Notification Configuration Example](https://raw.githubusercontent.com/cobryan05/ha-color-notify/refs/heads/main/images/notification_options.png?raw=true)](https://raw.githubusercontent.com/cobryan05/ha-color-notify/refs/heads/main/images/notification_options.png?raw=true)

#### Notification Options
* **Priority:** Numerical ranking determining which active notification takes visual precedence.
* **Temporary Display on Activation:** Forces the notification to briefly take over the light upon activation, regardless of its priority ranking.
* **Automatic Clear After Timeout:** Automatically turns off the notification switch after a set duration. A timeout value of `0` will automatically clear the switch immediately after the animation pattern completes its run.
* **Color:** Applies a static, solid RGB color to the notification.
* **Pattern:** Build complex animations using a sequence of JSON steps containing colors and delays:
  * **Loops:** Use `[` to open a loop and `], loopcnt` to close and define its repetitions (e.g., `], 5` runs that segment five times).
  * **Steps:** Format individual color blocks with RGB values and duration in seconds (e.g., `{"rgb": [255,0,0], "delay": 0.5}` flashes red for half a second).

---

## Usage

1. Create a **Notification Pool** to host your custom alert profiles.
2. Edit your **Light Wrapper** settings to subscribe it to individual alerts or entire notification pools.
3. Trigger an alert from an automation, script, or dashboard by simply turning on the respective `switch` entity.

[![Light Subscription Example](https://raw.githubusercontent.com/cobryan05/ha-color-notify/refs/heads/main/images/subscriptions.png?raw=true)](https://raw.githubusercontent.com/cobryan05/ha-color-notify/refs/heads/main/images/subscriptions.png?raw=true)

---

## Fuel the Development

This project is open-source and free to use. If it saves you time or automates your home a little better, [GitHub Sponsorships](https://github.com/sponsors/cobryan05) (both one-time tips and recurring) are always appreciated but never required.

### Feedback & Ideas
I’d love to hear how you're using this integration! Whether you have a feature idea, ran into a bug, or just want to share your automation setup, feel free to open an [Issue](https://github.com/cobryan05/ha-color-notify/issues) or join the [Discussions](https://github.com/cobryan05/ha-color-notify/discussions). Hearing how it works in the wild keeps the project moving forward.
