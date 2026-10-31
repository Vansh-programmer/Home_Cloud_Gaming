#!/bin/sh
set -eu

mkdir -p /data/cfg
cp /source/config.toml /data/cfg/config.toml
if [ -f /source/key.pem ]; then
    cp /source/key.pem /data/cfg/key.pem
    chmod 600 /data/cfg/key.pem
fi
if [ -f /source/cert.pem ]; then
    cp /source/cert.pem /data/cfg/cert.pem
    chmod 644 /data/cfg/cert.pem
fi
chmod 644 /data/cfg/config.toml
