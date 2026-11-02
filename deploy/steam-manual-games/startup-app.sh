#!/bin/bash
set -e

source /opt/gow/bash-lib/utils.sh

gow_log "Steam startup.sh (with Ryoku manual game sync)"

# Remove stale Chromium SingletonLocks left by previous container hostnames
rm -f "$HOME/.steam/steam/config/htmlcache/Singleton"* \
      "$HOME/.local/share/Steam/config/htmlcache/Singleton"* \
      "$HOME/.steam/steam.pid" \
      "$HOME/.Position" 2>/dev/null || true

# Sync manually downloaded games from /shared_games (:ro) into Steam shortcuts & library
if [ -f /opt/gow/ryoku-steam-sync.py ]; then
  /usr/bin/python3 /opt/gow/ryoku-steam-sync.py || true
  /usr/bin/python3 /opt/gow/ryoku-steam-sync.py --watch &
fi

# Recursively creating Steam necessary folders (https://github.com/ValveSoftware/steam-for-linux/issues/6492)
mkdir -p "$HOME/.steam/ubuntu12_32/steam-runtime"
mkdir -p "$HOME/.local/share/ryoku-games"

# Use the new big picture mode by default
STEAM_STARTUP_FLAGS=${STEAM_STARTUP_FLAGS:-"-bigpicture"}

# Some game fixes taken from the Steam Deck
export SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0

# Enable Mangoapp
export STEAM_USE_MANGOAPP=1
export MANGOHUD_CONFIGFILE=$(mktemp /tmp/mangohud.XXXXXXXX)
export STEAM_MANGOAPP_HORIZONTAL_SUPPORTED=1

# Enable Variable Rate Shading
export STEAM_USE_DYNAMIC_VRS=1
export RADV_FORCE_VRS_CONFIG_FILE=$(mktemp /tmp/radv_vrs.XXXXXXXX)
export WINEDLLOVERRIDES=dxgi=n

mkdir -p "$(dirname "$MANGOHUD_CONFIGFILE")"
echo "position=top-right" > "$MANGOHUD_CONFIGFILE"
echo "no_display" >> "$MANGOHUD_CONFIGFILE"

mkdir -p "$(dirname "$RADV_FORCE_VRS_CONFIG_FILE")"
echo "1x1" > "$RADV_FORCE_VRS_CONFIG_FILE"

export STEAM_GAMESCOPE_FANCY_SCALING_SUPPORT=1
export SRT_URLOPEN_PREFER_STEAM=1
export QT_IM_MODULE=steam
export GTK_IM_MODULE=Steam

if [ -n "$RUN_SWAY" ]; then
  /usr/bin/ibus-daemon -d -r --panel=disable --emoji-extension=disable
  export MANGOHUD=${MANGOHUD:-1}
  source /opt/gow/launch-comp.sh
  launcher /usr/games/steam ${STEAM_STARTUP_FLAGS}
else
  exec /usr/games/steam ${STEAM_STARTUP_FLAGS}
fi
