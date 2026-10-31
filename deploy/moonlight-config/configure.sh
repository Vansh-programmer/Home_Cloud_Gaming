#!/bin/sh
set -eu

settings_dir=/data/.local/share/MoonlightWeb/MoonlightWeb
settings_file="$settings_dir/settings.json"
temporary_file="$settings_file.tmp"

mkdir -p "$settings_dir"
if [ -s "$settings_file" ]; then
  jq '.domain = "play.vanshdev.online" | .setup_completed = true | .native_host_enabled = false | .cert_auth_enabled = true' "$settings_file" > "$temporary_file"
else
  printf '{"domain":"play.vanshdev.online","setup_completed":true,"native_host_enabled":false,"cert_auth_enabled":true}\n' > "$temporary_file"
fi
chmod 600 "$temporary_file"
mv "$temporary_file" "$settings_file"
