#!/usr/bin/env python3
"""
RYOKU CLOUD GAMING // INSTANT WOLF PAIRING HELPER
=================================================
Automates Moonlight / Moonlight Web pairing by extracting the active
pairing session secret from Wolf and submitting the user's PIN instantly.

Usage:
  python3 deploy/pair.py <4-DIGIT-PIN>
"""

import re
import sys
import json
import subprocess
import urllib.request

def pair(pin: str) -> bool:
    pin = pin.strip()
    if not pin.isdigit() or len(pin) != 4:
        print(f"[ERROR] PIN must be exactly 4 digits, got: '{pin}'")
        return False

    print(f"[INFO] Looking for active Wolf pairing session for PIN {pin}...")
    try:
        logs = subprocess.check_output(
            ["docker", "logs", "ryoku-cloud-server", "--tail", "25"],
            stderr=subprocess.STDOUT,
            text=True
        )
    except Exception as e:
        print(f"[ERROR] Failed to read Wolf logs: {e}")
        return False

    # Extract all pairing URLs and get the most recent one
    # Format: Insert pin at http://192.168.1.5:47989/pin/#<SECRET>
    matches = re.findall(r"Insert pin at http://[^/]+/pin/#([A-Fa-f0-9]+)", logs)
    if not matches:
        print("[WARNING] No active pairing request found in Wolf logs.")
        print("Please click on 'Wolf' in Moonlight Web to initiate pairing, then run this script.")
        return False

    secret = matches[-1]
    print(f"[OK] Found active pairing session secret: {secret}")

    url = "http://127.0.0.1:47989/pin/"
    payload = json.dumps({"pin": pin, "secret": secret}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            if "OK" in body or resp.status == 200:
                print(f"[SUCCESS] Host paired successfully! (Server response: {body.strip()})")
                print("Your Moonlight client is now unlocked and ready to stream.")
                return True
            else:
                print(f"[ERROR] Pairing rejected by Wolf: {body}")
                return False
    except Exception as e:
        print(f"[ERROR] Failed to send PIN to Wolf: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 deploy/pair.py <4-DIGIT-PIN>")
        sys.exit(1)
    success = pair(sys.argv[1])
    sys.exit(0 if success else 1)

