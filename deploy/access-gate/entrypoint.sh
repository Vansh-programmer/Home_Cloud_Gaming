#!/bin/sh
set -eu

# MoonlightWeb binds its HTTP control ports to every host interface. Keep those
# ports reachable only through loopback, where the authenticated Caddy proxy
# connects. The dedicated table survives gate restarts and is recreated after
# a host reboot when this container starts.
nft list table inet ryoku_cloud_gate >/dev/null 2>&1 || nft add table inet ryoku_cloud_gate
nft list chain inet ryoku_cloud_gate direct_ports >/dev/null 2>&1 || \
  nft add chain inet ryoku_cloud_gate direct_ports '{ type filter hook input priority -50; policy accept; }'
nft list chain inet ryoku_cloud_gate direct_ports 2>/dev/null | \
  grep -Fq 'tcp dport { 8080, 8443 } drop' || \
  nft add rule inet ryoku_cloud_gate direct_ports iifname != lo tcp dport '{' 8080, 8443 '}' drop
nft list chain inet ryoku_cloud_gate direct_ports 2>/dev/null | \
  grep -Fq 'tcp dport { 47984, 47989, 47990, 48010 } drop' || \
  nft add rule inet ryoku_cloud_gate direct_ports iifname != lo tcp dport '{' 47984, 47989, 47990, 48010 '}' drop
nft list chain inet ryoku_cloud_gate direct_ports 2>/dev/null | \
  grep -Fq 'udp dport { 47998, 47999, 48000, 48010 } drop' || \
  nft add rule inet ryoku_cloud_gate direct_ports iifname != lo udp dport '{' 47998, 47999, 48000, 48010 '}' drop

exec /usr/local/bin/access-gate
