#!/bin/bash
set -e

source /opt/gow/bash-lib/utils.sh

export SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export __GL_THREADED_OPTIMIZATIONS=1
export __GL_YIELD="USLEEP"
export __GL_MaxFramesAllowed=1
export PULSE_LATENCY_MSEC=20

GAME_CMD="${RYOKU_GAME_CMD:-supertux2 --fullscreen --renderer opengl}"
gow_log "[Ryoku Linux Games] Launching: ${GAME_CMD}"

# Pre-seed fullscreen configs for games that read user config files
mkdir -p "$HOME/.etr" "$HOME/.neverball" "$HOME/.minetest"
if [ ! -f "$HOME/.etr/options.txt" ]; then
  cat << 'EOF' > "$HOME/.etr/options.txt"
[fullscreen] 1
[res_type] 0
[framerate] 60
EOF
fi
if [ ! -f "$HOME/.neverball/neverballrc" ]; then
  cat << 'EOF' > "$HOME/.neverball/neverballrc"
fullscreen 1
width 1920
height 1080
vsync 1
EOF
fi
if [ ! -f "$HOME/.minetest/minetest.conf" ]; then
  cat << 'EOF' > "$HOME/.minetest/minetest.conf"
fullscreen = true
screen_w = 1920
screen_h = 1080
fps_max = 60
vsync = true
EOF
fi

source /opt/gow/launch-comp.sh
launcher $GAME_CMD

