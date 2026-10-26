#!/usr/bin/env python3
"""
TURN relay self-test for Ryoku Cloud Gaming.

Reads the same configuration the server uses (.env + data/network_config.json), then performs
a real TURN `Allocate` (RFC 5766 long-term credentials) against every configured relay URL over
UDP and TCP. This proves, from THIS PC, that:
  1. the relay host resolves and is reachable,
  2. the username / password are accepted,
  3. a relay address can actually be allocated (what remote players depend on).

Usage:
    python3 engine/turn_check.py
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import socket
import struct
import sys
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.network_manager import NetworkConfigManager  # noqa: E402

MAGIC = 0x2112A442
ALLOCATE_REQ = 0x0003
ALLOCATE_OK = 0x0103
ALLOCATE_ERR = 0x0113
ATTR_USERNAME = 0x0006
ATTR_INTEGRITY = 0x0008
ATTR_ERROR = 0x0009
ATTR_REALM = 0x0014
ATTR_NONCE = 0x0015
ATTR_XOR_RELAYED = 0x0016
ATTR_REQ_TRANSPORT = 0x0019


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _attr(atype: int, value: bytes) -> bytes:
    pad = (4 - len(value) % 4) % 4
    return struct.pack("!HH", atype, len(value)) + value + b"\x00" * pad


def build_allocate(
    txid: bytes,
    username: str = "",
    realm: bytes = b"",
    nonce: bytes = b"",
    password: str = "",
) -> bytes:
    body = _attr(ATTR_REQ_TRANSPORT, b"\x11\x00\x00\x00")  # UDP relay
    if username:
        body += _attr(ATTR_USERNAME, username.encode())
        body += _attr(ATTR_REALM, realm)
        body += _attr(ATTR_NONCE, nonce)
        # MESSAGE-INTEGRITY covers header (with length incl. the 24-byte integrity attr) + body
        header = struct.pack("!HHI", ALLOCATE_REQ, len(body) + 24, MAGIC) + txid
        key = hashlib.md5(f"{username}:{realm.decode()}:{password}".encode()).digest()
        mac = hmac.new(key, header + body, hashlib.sha1).digest()
        body += _attr(ATTR_INTEGRITY, mac)
    return struct.pack("!HHI", ALLOCATE_REQ, len(body), MAGIC) + txid + body


def parse_attrs(data: bytes) -> Tuple[int, Dict[int, bytes]]:
    mtype, length = struct.unpack("!HH", data[:4])
    attrs: Dict[int, bytes] = {}
    pos = 20
    end = 20 + length
    while pos + 4 <= end and pos + 4 <= len(data):
        atype, alen = struct.unpack("!HH", data[pos : pos + 4])
        attrs[atype] = data[pos + 4 : pos + 4 + alen]
        pos += 4 + alen + (4 - alen % 4) % 4
    return mtype, attrs


def exchange(sock: socket.socket, payload: bytes, tcp: bool) -> bytes:
    if tcp:
        sock.sendall(payload)
        head = b""
        while len(head) < 20:
            chunk = sock.recv(20 - len(head))
            if not chunk:
                raise ConnectionError("relay closed TCP connection")
            head += chunk
        length = struct.unpack("!H", head[2:4])[0]
        body = b""
        while len(body) < length:
            chunk = sock.recv(length - len(body))
            if not chunk:
                raise ConnectionError("relay closed TCP connection")
            body += chunk
        return head + body
    sock.send(payload)
    return sock.recv(2048)


def check_one(url: str, username: str, password: str, timeout: float = 5.0) -> Tuple[bool, str]:
    parsed = urllib.parse.urlsplit(url)  # e.g. turn:host:3478?transport=tcp
    scheme = parsed.scheme
    rest = parsed.path or parsed.netloc
    host, _, port_s = rest.partition(":")
    port = int(port_s) if port_s else (5349 if scheme == "turns" else 3478)
    query = urllib.parse.parse_qs(parsed.query)
    tcp = query.get("transport", ["udp"])[0] == "tcp" or scheme == "turns"
    if scheme == "turns":
        return False, "turns (TLS) not covered by this quick check; use the TCP/UDP URLs"

    try:
        addr = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM)[0]
    except OSError as exc:
        return False, f"DNS failure for {host}: {exc}"

    sock = socket.socket(addr[0], socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.connect(addr[4])
        txid = secrets.token_bytes(12)
        resp = exchange(sock, build_allocate(txid), tcp)
        mtype, attrs = parse_attrs(resp)
        if mtype == ALLOCATE_OK:
            return True, "relay allocated without auth (open relay)"
        if ATTR_REALM not in attrs or ATTR_NONCE not in attrs:
            return False, f"unexpected reply type 0x{mtype:04x} (no realm/nonce)"
        realm, nonce = attrs[ATTR_REALM], attrs[ATTR_NONCE]

        txid2 = secrets.token_bytes(12)
        resp2 = exchange(sock, build_allocate(txid2, username, realm, nonce, password), tcp)
        mtype2, attrs2 = parse_attrs(resp2)
        if mtype2 == ALLOCATE_OK:
            return True, "relay allocation OK (credentials accepted)"
        if mtype2 == ALLOCATE_ERR and ATTR_ERROR in attrs2:
            code = attrs2[ATTR_ERROR][2] * 100 + attrs2[ATTR_ERROR][3]
            reason = attrs2[ATTR_ERROR][4:].decode(errors="replace")
            hint = " (wrong username/password)" if code == 401 else ""
            return False, f"relay rejected Allocate: {code} {reason}{hint}"
        return False, f"unexpected reply type 0x{mtype2:04x}"
    except socket.timeout:
        return False, "timed out (port blocked by this PC's network or relay down)"
    except OSError as exc:
        return False, f"network error: {exc}"
    finally:
        sock.close()


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    mgr = NetworkConfigManager()

    print("RYOKU TURN RELAY CHECK")
    print("=" * 60)
    print(f"container ICE enabled : {mgr.enable_container_ice}")
    print(f"STUN                  : {mgr.stun_url or '(none)'}")

    targets: List[Tuple[str, str, str]] = []
    if mgr.cloudflare_turn_configured:
        for server in mgr.fetch_cloudflare_ice_servers():
            urls = server.get("urls", [])
            urls = [urls] if isinstance(urls, str) else urls
            for u in urls:
                if str(u).startswith("turn:"):
                    targets.append((str(u), str(server.get("username", "")), str(server.get("credential", ""))))
        if not targets:
            print(f"Cloudflare TURN error : {mgr._cf_last_error or 'no servers returned'}")

    if mgr.turn_url:
        urls = mgr.parse_turn_urls(mgr.turn_url)
        if mgr.turn_username and mgr.turn_password:
            user, pw = mgr.turn_username, mgr.turn_password
        elif mgr.turn_secret:
            creds = mgr.generate_turn_rest_credentials("check")
            user, pw = str(creds["username"]), str(creds["credential"])
        else:
            user, pw = "", ""
        print(f"TURN URL(s) (as sent) : {', '.join(urls)}")
        print(f"TURN credentials      : {'set' if user and pw else 'MISSING (username/password empty)'}")
        for u in urls:
            if u.startswith("turn:"):
                targets.append((u, user, pw))

    if not targets:
        print("\nRESULT: NO TURN RELAY CONFIGURED. Remote (outside-network) video cannot work.")
        print("Set TURN_URL / TURN_USERNAME / TURN_PASSWORD in .env, then restart.")
        return 2

    print("\nTesting relays (real TURN Allocate request):")
    any_ok = False
    for url, user, pw in targets:
        ok, msg = check_one(url, user, pw)
        any_ok = any_ok or ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {url}  ->  {msg}")

    print()
    if any_ok:
        print("RESULT: PASS. At least one relay works from this PC.")
        return 0
    print("RESULT: FAIL. No relay worked. Fix the URL/credentials above (see FAIL reasons).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
