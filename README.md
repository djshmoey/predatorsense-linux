# PredatorSense Linux

<div align="center">

**A full PredatorSense replacement GUI for the Acer Predator PHN16S-71 on Linux**

[![License: GPL v2](https://img.shields.io/badge/License-GPL%20v2-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html)
[![Platform](https://img.shields.io/badge/Platform-Linux-orange.svg)](https://kernel.org)
[![Distro](https://img.shields.io/badge/Distro-CachyOS%20%7C%20Arch-blue.svg)](https://cachyos.org)
[![GTK](https://img.shields.io/badge/GTK-4.0%20%2F%20Adwaita-orange.svg)](https://gtk.org)

</div>

---

## ✨ Features

| Feature | Status |
|---|---|
| 📊 Live system monitoring (CPU, GPU, RAM, Battery) | ✅ |
| 🌀 Fan speed control (CPU + GPU independent) | ✅ |
| 🔥 Thermal profiles (Quiet / Balanced / Performance / Turbo) | ✅ |
| ⌨️ Keyboard backlight timeout & boot animation toggle | ✅ |
| 🔋 Battery limiter (80% charge cap) + calibration | ✅ |
| 🔌 USB sleep charging control | ✅ |
| 🖥️ LCD override (MUX switch) | ✅ |
| 🎮 GPU mode switching (Integrated / Hybrid / NVIDIA) | ✅ |
| ⚡ Quick profile switcher in headerbar | ✅ |
| 🌙 Dark & Light mode toggle | ✅ |
| 🚀 Autostart on login | ✅ |
| ⌨️ Hardware keyboard button to cycle profiles | ✅ |

---

## 🖥️ Requirements

- **Laptop:** Acer Predator PHN16S-71
- **OS:** CachyOS or any Arch-based Linux distro
- **Kernel:** Linux 7.0+ (cachyos kernel recommended)
- **Desktop:** GNOME (Wayland or X11)
- **AUR Helper:** `paru` or `yay` (recommended)

---

## ⚡ Quick Install

```bash
git clone https://github.com/djshmoey/predatorsense-linux
cd predatorsense-linux
chmod +x install.sh
./install.sh
```

Reboot and launch:

```bash
predatorsense
```

Or search **"PredatorSense"** in your GNOME app grid.

> **No internet required after cloning.** The `linuwu_sense` kernel driver is bundled locally in the `driver/` folder — the installer uses it directly without downloading anything extra.

---

## 📦 Step-by-Step Installation

### Step 1 — Clone the repository

```bash
git clone https://github.com/djshmoey/predatorsense-linux
cd predatorsense-linux
```

### Step 2 — Run the installer

```bash
chmod +x install.sh
./install.sh
```

The installer automatically:

- Detects your CachyOS kernel variant and installs correct headers
- Builds and installs the **linuwu_sense** kernel module via DKMS
- Sets `predator_v4=Y` module parameter (required for PHN16S-71)
- Blacklists the conflicting `acer_wmi` module
- Installs **EnvyControl** for GPU mode switching
- Configures **lm-sensors** for temperature monitoring
- Sets up `udev` rules and `sudoers` for passwordless hardware control
- Installs the Python GTK4 GUI and creates a desktop launcher

### Step 3 — Make the module parameter permanent

```bash
echo "options linuwu_sense predator_v4=Y" | sudo tee /etc/modprobe.d/linuwu-sense-options.conf
```

### Step 4 — Add yourself to the input group

Required for the profile cycle keyboard button:

```bash
sudo usermod -aG input $USER
```

Log out and back in for this to take effect.

### Step 5 — Reboot

```bash
sudo reboot
```

### Step 6 — Launch

```bash
predatorsense
```

---

## ⌨️ Profile Cycle Keyboard Button

Press the **Predator Logo Key** to instantly cycle through thermal profiles without opening the app.

The Predator Logo Key is located in the **top-right media cluster, immediately to the left of NumLk**.

> `KEY_PRESENTATION` · code `425` · scancode `0xF5` · device `/dev/input/event2`

**Cycles through:**
```
🤫 Quiet  →  ⚖ Balanced  →  ⚡ Performance  →  🔥 Turbo  →  🔁
```

> **Note:** Performance and Turbo require AC power. Pressing the button while on battery will only cycle between Quiet and Balanced — this matches official Windows PredatorSense behavior.

---

## 🔥 Thermal Profiles

| Profile | Kernel Value | Fan Speed | AC Required |
|---|---|---|---|
| 🤫 Quiet | `low-power` | Minimal / EC managed | No |
| ⚖ Balanced | `balanced` | Auto | No |
| ⚡ Performance | `balanced-performance` | High | **Yes** |
| 🔥 Turbo | `performance` | Maximum | **Yes** |

---

## 🌀 Fan Control

Control CPU and GPU fans independently via sliders (0–100%).

Quick presets:

| Preset | CPU Fan | GPU Fan | Thermal |
|---|---|---|---|
| Turbo | 100% | 100% | Turbo |
| Performance | 80% | 80% | Performance |
| Balanced | 50% | 50% | Balanced |
| Quiet | 0% | 0% | Quiet |

---

## 🎮 GPU Mode Switching

| Mode | Description | Reboot Required |
|---|---|---|
| Integrated | Intel GPU only — best battery life | Yes |
| Hybrid | Intel default, NVIDIA on-demand | Yes |
| NVIDIA Only | Discrete GPU — max performance | Yes |

---

## 🔋 Battery

- **80% Limiter** — Caps charging at 80% to preserve long-term battery health
- **Calibration** — Full charge/discharge cycle to recalibrate battery gauge
- **USB Sleep Charging** — Charge devices while laptop is suspended (5W / 10W / 20W / 45W)

---

## 🔧 Driver Notes

- Uses **linuwu_sense** kernel module from [Linuwu-Sense](https://github.com/0x7375646F/Linuwu-Sense) / [DAMX 0.9.1](https://github.com/Div-Sharp/DAMX)
- DKMS ensures the module rebuilds automatically on kernel updates
- `predator_v4=Y` parameter is required for PHN16S-71 to expose sysfs fan/thermal controls
- The app detects both `predator_sense` and `nitro_sense` sysfs paths automatically

---

## 🛠️ Troubleshooting

**Driver not found / warning shown:**
```bash
sudo rmmod linuwu_sense
sudo modprobe linuwu_sense predator_v4=Y
ls /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/
```

**DKMS build failed:**
```bash
sudo pacman -S linux-cachyos-headers clang llvm
sudo dkms autoinstall
```

**Fan/battery controls not working (permission denied):**
```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

**Profile button not cycling:**
```bash
# Make sure you're in the input group
groups | grep input
# If not:
sudo usermod -aG input $USER
# Then log out and back in
```

**GPU mode not applying:**
```bash
sudo envycontrol --switch hybrid
# Then log out and back in
```

---

## 🗑️ Uninstall

```bash
chmod +x uninstall.sh
./uninstall.sh
```

---

## 📄 License

GPL v2 — same license as the Linux kernel.

---

## 📋 Changelog

### v1.2
- Custom fan profiles — create, name and delete your own fan curves
- Fan speeds automatically sync when switching thermal profiles
- Delete button on custom profiles with confirmation dialog
- Reset individual or all profiles to defaults

### v1.1
- 10-point interactive fan curve editor per thermal profile (Quiet/Balanced/Performance/Turbo)
- Independent CPU and GPU fan curves
- Auto Fan Curve mode — fans adjust automatically based on temperature
- Live curve updates — drag points and fans respond instantly
- Save / Reset buttons per curve

### v1.0
- Initial release
- Full fan, thermal, battery, display, keyboard, GPU mode control
- Predator Logo Key cycles profiles
- Dark/Light mode, autostart, background mode

---

## 🙏 Credits

- [Linuwu-Sense](https://github.com/0x7375646F/Linuwu-Sense) — WMI kernel module base
- [DAMX](https://github.com/Div-Sharp/DAMX) — DAMX 0.9.1 with PHN16S-71 support
- [EnvyControl](https://github.com/bayasdev/envycontrol) — GPU mode switching
- [python-gobject](https://pygobject.gnome.org/) — GTK4 Python bindings
