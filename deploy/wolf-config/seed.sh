#!/bin/sh
set -eu

mkdir -p /data/cfg
SHARED_PATH="${HOST_SHARED_GAMES_PATH:-/home/vansh/Projects/Home_Cloud_Gaming/data/shared_games}"
sed "s|/home/vansh/Projects/Home_Cloud_Gaming/data/shared_games|${SHARED_PATH}|g" /source/config.toml > /data/cfg/config.toml
if [ -f /source/key.pem ]; then
    cp /source/key.pem /data/cfg/key.pem
    chmod 600 /data/cfg/key.pem
fi
if [ -f /source/cert.pem ]; then
    cp /source/cert.pem /data/cfg/cert.pem
    chmod 644 /data/cfg/cert.pem
fi
chmod 644 /data/cfg/config.toml
