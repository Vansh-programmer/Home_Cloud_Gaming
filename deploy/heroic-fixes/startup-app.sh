#!/bin/bash
set -e

# Ensure Valve Proton (Proton-Experimental) has native steamclient.so inside Heroic's isolated $HOME
if [ -d /opt/gow/steamclient ]; then
  mkdir -p "$HOME/.steam/steam/ubuntu12_64" \
           "$HOME/.steam/steam/ubuntu12_32" \
           "$HOME/.steam/steam/linux64" \
           "$HOME/.steam/steam/linux32"
  for dst in "$HOME/.steam/steam/ubuntu12_64/steamclient.so" "$HOME/.steam/steam/linux64/steamclient.so"; do
    if [ ! -f "$dst" ]; then
      ln -sf /opt/gow/steamclient/linux64/steamclient.so "$dst"
    fi
  done
  for dst in "$HOME/.steam/steam/ubuntu12_32/steamclient.so" "$HOME/.steam/steam/linux32/steamclient.so"; do
    if [ ! -f "$dst" ]; then
      ln -sf /opt/gow/steamclient/linux32/steamclient.so "$dst"
    fi
  done
fi

export PROTON_USE_XALIA=0
export STEAM_COMPAT_MOUNTS=/shared_games

source /opt/gow/launch-comp.sh
launcher /usr/bin/heroic ${HEROIC_STARTUP_FLAGS} --no-sandbox

