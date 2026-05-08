#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║        PredatorSense Linux — Installer for Acer PHN16S-71 / CachyOS        ║
# ║    Installs: linuwu_sense driver · DKMS · Python GUI · Desktop launcher    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
set -euo pipefail

BOLD='\033[1m'; RED='\033[0;31m'; GREEN='\033[0;32m'
YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

banner() {
  echo -e "${CYAN}"
  echo "  ██████╗ ██████╗ ███████╗██████╗  █████╗ ████████╗ ██████╗ ██████╗ "
  echo "  ██╔══██╗██╔══██╗██╔════╝██╔══██╗██╔══██╗╚══██╔══╝██╔═══██╗██╔══██╗"
  echo "  ██████╔╝██████╔╝█████╗  ██║  ██║███████║   ██║   ██║   ██║██████╔╝"
  echo "  ██╔═══╝ ██╔══██╗██╔══╝  ██║  ██║██╔══██║   ██║   ██║   ██║██╔══██╗"
  echo "  ██║     ██║  ██║███████╗██████╔╝██║  ██║   ██║   ╚██████╔╝██║  ██║"
  echo "  ╚═╝     ╚═╝  ╚═╝╚══════╝╚═════╝ ╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝"
  echo -e "${NC}"
  echo -e "  ${BOLD}PredatorSense Linux — Installer${NC}"
  echo -e "  For: Acer Predator series · CachyOS / Arch Linux"
  echo ""
}

log()  { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; }
err()  { echo -e "  ${RED}✗${NC}  $1"; }
step() { echo -e "\n  ${CYAN}━━ $1 ${NC}"; }

check_root() {
  if [[ $EUID -eq 0 ]]; then
    err "Do not run this script as root. It will use sudo when needed."
    exit 1
  fi
}

check_hardware() {
  MODEL=$(cat /sys/class/dmi/id/product_name 2>/dev/null || echo "Unknown")
  log "Hardware model: $MODEL"
  if echo "$MODEL" | grep -qi "predator\|nitro"; then
    log "Acer Predator/Nitro laptop detected ✓"
  else
    warn "This app is designed for Acer Predator/Nitro laptops."
    warn "Detected: $MODEL"
    warn "Installation will continue but hardware controls may not work."
    echo ""
    read -rp "  Continue anyway? [y/N] " hw_confirm
    [[ "${hw_confirm,,}" != "y" ]] && { echo "  Aborted."; exit 0; }
  fi
}

check_distro() {
  DISTRO=$(grep -oP "(?<=^ID=).*" /etc/os-release 2>/dev/null | tr -d '"' || echo "unknown")
  DISTRO_LIKE=$(grep -oP "(?<=^ID_LIKE=).*" /etc/os-release 2>/dev/null | tr -d '"' || echo "")

  if echo "$DISTRO $DISTRO_LIKE" | grep -qi "cachyos"; then
    DISTRO_NAME="CachyOS"
    PKG_MANAGER="pacman"
  elif echo "$DISTRO $DISTRO_LIKE" | grep -qi "arch\|manjaro\|endeavour\|garuda\|artix"; then
    DISTRO_NAME="Arch-based ($DISTRO)"
    PKG_MANAGER="pacman"
  elif echo "$DISTRO $DISTRO_LIKE" | grep -qi "ubuntu\|debian\|mint\|pop"; then
    DISTRO_NAME="Debian-based ($DISTRO)"
    PKG_MANAGER="apt"
    warn "Debian/Ubuntu detected. Some packages may have different names."
    warn "The installer will attempt to use apt where possible."
  elif echo "$DISTRO $DISTRO_LIKE" | grep -qi "fedora\|rhel\|centos"; then
    DISTRO_NAME="Fedora-based ($DISTRO)"
    PKG_MANAGER="dnf"
    warn "Fedora detected. Some packages may have different names."
  else
    DISTRO_NAME="Unknown ($DISTRO)"
    PKG_MANAGER="pacman"
    warn "Unknown distro. Assuming pacman-based. Install may fail."
  fi
  log "Distro: $DISTRO_NAME"
}

detect_kernel_headers() {
  KERNEL=$(uname -r)
  log "Kernel: $KERNEL"

  # Detect correct headers package based on kernel variant
  if echo "$KERNEL" | grep -q "cachyos-lto"; then
    HEADERS_PKG="linux-cachyos-lto-headers"
  elif echo "$KERNEL" | grep -q "cachyos-bore"; then
    HEADERS_PKG="linux-cachyos-bore-headers"
  elif echo "$KERNEL" | grep -q "cachyos-eevdf"; then
    HEADERS_PKG="linux-cachyos-eevdf-headers"
  elif echo "$KERNEL" | grep -q "cachyos"; then
    HEADERS_PKG="linux-cachyos-headers"
  elif echo "$KERNEL" | grep -q "zen"; then
    HEADERS_PKG="linux-zen-headers"
  elif echo "$KERNEL" | grep -q "lts"; then
    HEADERS_PKG="linux-lts-headers"
  elif echo "$KERNEL" | grep -q "hardened"; then
    HEADERS_PKG="linux-hardened-headers"
  else
    HEADERS_PKG="linux-headers"
  fi

  # For Debian/Ubuntu-based systems
  if [[ "${PKG_MANAGER:-pacman}" == "apt" ]]; then
    HEADERS_PKG="linux-headers-$(uname -r)"
  fi
  log "Kernel headers package: $HEADERS_PKG"
}

detect_compiler() {
  # CachyOS kernels are typically compiled with Clang
  if clang --version &>/dev/null; then
    COMPILER="clang"
    LLVM_FLAG="LLVM=1"
    log "Compiler: Clang/LLVM (optimal for CachyOS)"
  else
    COMPILER="gcc"
    LLVM_FLAG=""
    warn "Clang not found, falling back to GCC"
  fi
}

install_base_deps() {
  step "Installing base dependencies"
  if [[ "${PKG_MANAGER:-pacman}" == "pacman" ]]; then
    sudo pacman -Sy --needed --noconfirm       git base-devel dkms       python python-gobject python-pip       gtk4 libadwaita       lm_sensors       "$HEADERS_PKG" || {
      err "pacman install failed. Check your internet or mirrors."
      exit 1
    }
    if [[ "$COMPILER" == "clang" ]]; then
      sudo pacman -S --needed --noconfirm clang llvm lld || true
      log "Clang/LLVM installed"
    fi
  elif [[ "${PKG_MANAGER:-pacman}" == "apt" ]]; then
    sudo apt-get update -q
    sudo apt-get install -y       git build-essential dkms       python3 python3-gi python3-pip       gir1.2-gtk-4.0 gir1.2-adw-1       lm-sensors       "$HEADERS_PKG" || {
      err "apt install failed. Check your internet connection."
      exit 1
    }
  elif [[ "${PKG_MANAGER:-pacman}" == "dnf" ]]; then
    sudo dnf install -y       git dkms       python3 python3-gobject       gtk4 libadwaita       lm_sensors       "kernel-devel-$(uname -r)" || {
      err "dnf install failed."
      exit 1
    }
  fi
  log "Base dependencies installed"
}

install_python_deps() {
  step "Installing Python dependencies"
  # Prefer pacman packages
  sudo pacman -S --needed --noconfirm \
    python-gobject \
    python-cairo \
    2>/dev/null || true

  # nvidia monitoring
  if command -v nvidia-smi &>/dev/null; then
    log "nvidia-smi found — GPU monitoring enabled"
  else
    warn "nvidia-smi not in PATH — install nvidia-utils for GPU monitoring"
  fi

  log "Python dependencies ready"
}

install_linuwu_sense() {
  step "Installing linuwu_sense kernel module (via DKMS)"

  WORK_DIR="/tmp/linuwu-sense-build"
  rm -rf "$WORK_DIR"

  # Check for bundled driver first, then fall back to GitHub
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  DRIVER_DIR="$SCRIPT_DIR/driver"

  if [[ -f "$DRIVER_DIR/src/linuwu_sense.c" ]]; then
    log "Using bundled driver source"
    cp -r "$DRIVER_DIR" "$WORK_DIR"
  else
    log "Downloading DAMX 0.9.1 driver from GitHub..."
    DAMX_URL="https://github.com/PXDiv/Div-Acer-Manager-Max/releases/download/v0.9.1/DAMX-0.9.1.tar.xz"
    curl -L "$DAMX_URL" -o /tmp/DAMX-0.9.1.tar.xz || {
      err "Failed to download driver. Check your internet connection."
      exit 1
    }
    tar -xf /tmp/DAMX-0.9.1.tar.xz -C /tmp/
    cp -r /tmp/DAMX-0.9.1/Linuwu-Sense/. "$WORK_DIR"
    rm -f /tmp/DAMX-0.9.1.tar.xz
    rm -rf /tmp/DAMX-0.9.1
    log "DAMX 0.9.1 driver downloaded"
  fi

  cd "$WORK_DIR"

  # Detect version from Makefile or default
  MOD_VER=$(grep -oP '(?<=VERSION = ).*' Makefile 2>/dev/null | head -1 || echo "1.0.0")
  log "Module version: $MOD_VER"

  # Copy to DKMS source dir
  sudo mkdir -p "/usr/src/linuwu-sense-$MOD_VER"
  sudo cp -r . "/usr/src/linuwu-sense-$MOD_VER/"

  # Create dkms.conf if not present
  if true; then  # Always regenerate dkms.conf to ensure BUILT_MODULE_LOCATION is set
    sudo tee "/usr/src/linuwu-sense-$MOD_VER/dkms.conf" > /dev/null <<EOF
PACKAGE_NAME="linuwu-sense"
PACKAGE_VERSION="$MOD_VER"
BUILT_MODULE_NAME[0]="linuwu_sense"
BUILT_MODULE_LOCATION[0]="src/"
DEST_MODULE_LOCATION[0]="/kernel/drivers/platform/x86"
AUTOINSTALL="yes"
MAKE[0]="make ${LLVM_FLAG} -C \${kernel_source_dir} M=\${dkms_tree}/\${PACKAGE_NAME}/\${PACKAGE_VERSION}/build"
CLEAN="make -C \${kernel_source_dir} M=\${dkms_tree}/\${PACKAGE_NAME}/\${PACKAGE_VERSION}/build clean"
EOF
    log "Created dkms.conf"
  fi

  # Register and build
  sudo dkms add -m linuwu-sense -v "$MOD_VER" 2>/dev/null || true
  sudo dkms build -m linuwu-sense -v "$MOD_VER" --kernelsourcedir "/usr/lib/modules/$(uname -r)/build" || {
    err "DKMS build failed. Make sure kernel headers are installed for $(uname -r)"
    echo -e "  Try: ${YELLOW}sudo pacman -S $HEADERS_PKG${NC}"
    exit 1
  }
  sudo dkms install -m linuwu-sense -v "$MOD_VER" || {
    err "DKMS install failed."
    exit 1
  }
  log "linuwu_sense DKMS module installed"

  # Blacklist old acer_wmi and set required predator_v4=Y parameter
  sudo tee /etc/modprobe.d/acer-wmi-blacklist.conf > /dev/null <<EOF
# Blacklisted by PredatorSense Linux installer
# linuwu_sense replaces this module for Predator/Nitro laptops
blacklist acer_wmi
EOF
  # PHN16S-71 requires predator_v4=Y to expose sysfs fan/RGB controls
  echo "options linuwu_sense predator_v4=Y" | sudo tee /etc/modprobe.d/linuwu-sense-options.conf > /dev/null
  log "Blacklisted legacy acer_wmi module"
  log "Set predator_v4=Y module parameter"

  # Load the new module now
  sudo modprobe -r acer_wmi 2>/dev/null || true
  sudo modprobe linuwu_sense && log "linuwu_sense module loaded" || warn "Module load failed — may need reboot"

  cd -
  rm -rf "$WORK_DIR"
}

install_battery_module() {
  step "Installing acer-wmi-battery DKMS module (80% charge limit)"

  # Try AUR if paru/yay available
  if command -v paru &>/dev/null; then
    paru -S --needed --noconfirm acer-wmi-battery-dkms 2>/dev/null && {
      log "acer-wmi-battery installed via paru"
      return
    }
  elif command -v yay &>/dev/null; then
    yay -S --needed --noconfirm acer-wmi-battery-dkms 2>/dev/null && {
      log "acer-wmi-battery installed via yay"
      return
    }
  fi

  warn "AUR helper not found — battery module requires manual AUR install"
  warn "Install: paru -S acer-wmi-battery-dkms"
}

install_envycontrol() {
  step "Installing EnvyControl (GPU mode switcher)"

  if command -v envycontrol &>/dev/null; then
    log "EnvyControl already installed"
    return
  fi

  if command -v paru &>/dev/null; then
    paru -S --needed --noconfirm envycontrol 2>/dev/null && log "EnvyControl installed" && return
  elif command -v yay &>/dev/null; then
    yay -S --needed --noconfirm envycontrol 2>/dev/null && log "EnvyControl installed" && return
  fi

  # Fallback: pip install
  pip install envycontrol --break-system-packages 2>/dev/null && log "EnvyControl installed via pip" || \
    warn "EnvyControl install failed — GPU mode switching unavailable"
}

install_sensors() {
  step "Configuring lm-sensors"
  sudo sensors-detect --auto 2>/dev/null || true
  log "lm-sensors configured"
}

install_app() {
  step "Installing PredatorSense Linux GUI"

  INSTALL_DIR="$HOME/.local/share/predatorsense-linux"
  BIN_DIR="$HOME/.local/bin"
  mkdir -p "$INSTALL_DIR" "$BIN_DIR"

  # Copy app
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cp "$SCRIPT_DIR/src/predatorsense.py" "$INSTALL_DIR/"

  # Create launcher
  cat > "$BIN_DIR/predatorsense" <<'EOF'
#!/usr/bin/env bash
exec python3 "$HOME/.local/share/predatorsense-linux/predatorsense.py" "$@"
EOF
  chmod +x "$BIN_DIR/predatorsense"

  # Desktop entry
  mkdir -p "$HOME/.local/share/applications"
  cat > "$HOME/.local/share/applications/predatorsense.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=PredatorSense Linux
Comment=Fan, RGB, and power control for Acer Predator PHN16S-71
Exec=$BIN_DIR/predatorsense
Icon=input-gaming
Categories=System;Settings;HardwareSettings;
Keywords=acer;predator;fan;rgb;gaming;
StartupNotify=true
EOF

  # Add ~/.local/bin to PATH in shell configs
  for RC in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.config/fish/config.fish"; do
    if [[ -f "$RC" ]] && ! grep -q '\.local/bin' "$RC"; then
      echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$RC"
    fi
  done

  # Autostart on login (GNOME autostart)
  mkdir -p "$HOME/.config/autostart"
  cat > "$HOME/.config/autostart/predatorsense.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PredatorSense Linux
Exec=$BIN_DIR/predatorsense
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=PredatorSense Linux — runs in background for Predator key support
StartupNotify=false
EOF
  log "Autostart entry created"

  # Systemd user service (starts before GNOME session, survives window close)
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/predatorsense.service" <<EOF
[Unit]
Description=PredatorSense Linux background daemon
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=$BIN_DIR/predatorsense
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable predatorsense.service
  log "Systemd user service installed and enabled"

  log "App installed to $INSTALL_DIR"
  log "Launcher: $BIN_DIR/predatorsense"
  log "Desktop entry created"
}

setup_udev() {
  step "Setting up udev rules (allow user access to sysfs controls)"
  sudo tee /etc/udev/rules.d/99-predatorsense.rules > /dev/null <<'EOF'
# PredatorSense Linux — Allow group 'users' to write fan/RGB/battery controls
SUBSYSTEM=="module", KERNEL=="linuwu_sense", RUN+="/bin/chmod -R a+rw /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/"
ACTION=="add", SUBSYSTEM=="platform", KERNEL=="acer-wmi", RUN+="/bin/chmod -R a+rw /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/"
EOF
  sudo udevadm control --reload-rules
  sudo udevadm trigger
  log "udev rules installed"
}

setup_sudo_rules() {
  step "Setting up passwordless sudo for specific hardware controls"
  sudo tee /etc/sudoers.d/predatorsense > /dev/null <<EOF
# PredatorSense Linux — targeted sudo rules
$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/tee /sys/module/linuwu_sense/*
$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/tee /sys/firmware/acpi/platform_profile
$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/modprobe linuwu_sense
$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/modprobe -r linuwu_sense
$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/envycontrol
EOF
  sudo chmod 440 /etc/sudoers.d/predatorsense
  log "Sudo rules configured (no password for hardware controls)"
}

post_install_summary() {
  echo ""
  echo -e "${CYAN}╔═══════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║          Installation Complete! 🎮                ║${NC}"
  echo -e "${CYAN}╚═══════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  ${GREEN}Installed components:${NC}"
  echo "    • linuwu_sense kernel module (DKMS, auto-rebuilds on kernel update)"
  echo "    • acer_wmi blacklisted (avoids conflicts)"
  echo "    • PredatorSense Linux GUI"
  echo "    • Desktop launcher (search 'PredatorSense' in your app menu)"
  echo "    • EnvyControl (GPU mode switching)"
  echo "    • lm-sensors (CPU/temperature monitoring)"
  echo "    • udev rules + sudo rules (passwordless hardware control)"
  echo ""
  echo -e "  ${YELLOW}Launch the app:${NC}"
  echo "    predatorsense"
  echo "    (or search 'PredatorSense' in GNOME app grid)"
  echo ""
  echo -e "  ${YELLOW}⚠ A reboot is recommended to ensure the driver${NC}"
  echo -e "  ${YELLOW}  loads cleanly and udev rules take effect.${NC}"
  echo ""
  read -rp "  Reboot now? [y/N] " answer
  if [[ "${answer,,}" == "y" ]]; then
    sudo reboot
  fi
}

# ── Main ─────────────────────────────────────────────────────────────────────
banner
check_root
check_distro
check_hardware
detect_kernel_headers
detect_compiler

echo -e "  ${BOLD}This will install:${NC}"
echo "    • linuwu_sense kernel module (DKMS)"
echo "    • acer-wmi-battery module"
echo "    • EnvyControl GPU switcher"
echo "    • Python GTK4 GUI app"
echo "    • lm-sensors, nvidia-utils"
echo ""
read -rp "  Proceed? [Y/n] " confirm
[[ "${confirm,,}" == "n" ]] && { echo "  Aborted."; exit 0; }

install_base_deps
install_python_deps
install_linuwu_sense
install_battery_module
install_envycontrol
install_sensors
install_app
setup_udev
setup_sudo_rules
post_install_summary
