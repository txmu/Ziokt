#!/usr/bin/env bash
set -euo pipefail
package="${RUNNER_TEMP:?}/ziokt-i2pd_2.61.0.deb"
curl --fail --location --retry 3 --max-time 120 https://github.com/PurpleI2P/i2pd/releases/download/2.61.0/i2pd_2.61.0-1noble1_amd64.deb --output "$package"
printf '%s  %s\n' 5d4138be6cb448c1d59bba8c1e67e99f6cdbfea3e6f8697d3cce0252cfe24cf8 "$package" | sha256sum --check -
sudo apt-get install -y "$package"
sudo systemctl stop i2pd || true
if sudo test -r /sys/kernel/security/apparmor/profiles; then
  for profile in i2pd /usr/bin/i2pd /usr/sbin/i2pd; do
    if sudo awk -v profile="$profile" 'index($0, profile " (")==1 {found=1} END {exit !found}' /sys/kernel/security/apparmor/profiles; then
      printf 'profile "%s" {}\n' "$profile" | sudo apparmor_parser --remove
    fi
  done
fi
ZIOKT_I2P_LIVE=1 python -m unittest discover -s tests -p test_i2p_live.py -v
