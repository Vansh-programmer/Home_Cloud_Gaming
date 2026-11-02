#!/bin/sh
set -eu

mkdir -p /data/cfg
PROJECT_ROOT="${HOST_PROJECT_ROOT:-/home/vansh/Projects/Home_Cloud_Gaming}"
SHARED_PATH="${HOST_SHARED_GAMES_PATH:-${PROJECT_ROOT}/data/shared_games}"
sed -e "s|/home/vansh/Projects/Home_Cloud_Gaming/data/shared_games|${SHARED_PATH}|g" \
    -e "s|/home/vansh/Projects/Home_Cloud_Gaming|${PROJECT_ROOT}|g" \
    /source/config.toml > /data/cfg/config.toml
if [ -f /source/key.pem ]; then
    cp /source/key.pem /data/cfg/key.pem
    chmod 600 /data/cfg/key.pem
fi
if [ -f /source/cert.pem ]; then
    cp /source/cert.pem /data/cfg/cert.pem
    chmod 644 /data/cfg/cert.pem
fi
chmod 644 /data/cfg/config.toml
