#!/usr/bin/env bash
# PredatorSense Linux — Uninstaller
set -euo pipefail

echo "Removing PredatorSense Linux..."

# Remove DKMS module
MOD_VER=$(dkms status linuwu-sense 2>/dev/null | grep -oP '(?<=linuwu-sense, )[\d.]+' | head -1 || echo "")
if [[ -n "$MOD_VER" ]]; then
  sudo dkms remove linuwu-sense/"$MOD_VER" --all 2>/dev/null || true
  sudo rm -rf "/usr/src/linuwu-sense-$MOD_VER"
  echo "  ✓ linuwu_sense DKMS module removed"
fi

# Restore acer_wmi
sudo rm -f /etc/modprobe.d/acer-wmi-blacklist.conf
sudo modprobe acer_wmi 2>/dev/null || true
echo "  ✓ acer_wmi restored"

# Remove udev & sudo rules
sudo rm -f /etc/udev/rules.d/99-predatorsense.rules
sudo rm -f /etc/sudoers.d/predatorsense
sudo udevadm control --reload-rules

# Stop and remove systemd service
systemctl --user stop predatorsense.service 2>/dev/null || true
systemctl --user disable predatorsense.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/predatorsense.service"
systemctl --user daemon-reload

# Remove autostart
rm -f "$HOME/.config/autostart/predatorsense.desktop"

# Remove app files
rm -rf "$HOME/.local/share/predatorsense-linux"
rm -f  "$HOME/.local/bin/predatorsense"
rm -f  "$HOME/.local/share/applications/predatorsense.desktop"
rm -rf "$HOME/.config/predatorsense-linux"

echo "  ✓ App files removed"
echo ""
echo "PredatorSense Linux has been uninstalled. Reboot to restore defaults."
