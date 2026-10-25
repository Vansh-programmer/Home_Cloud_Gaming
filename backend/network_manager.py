"""
External HTTPS Access, STUN/TURN NAT Traversal & Offline Status Manager (Phase 6).

Responsibilities:
1. Generates browser W3C WebRTC `iceServers` configurations (`stun:` and `turn:`/`turns:`),
   including ephemeral time-limited HMAC-SHA1 TURN REST API credentials (`coturn` standard).
2. Formats GStreamer `webrtcbin` `stun-server` (`stun://host:port`) and `turn-server`
   (`turn://user:pass@host:port`) URIs for isolated game containers.
3. Manages external domain & Cloudflare Tunnel settings (`network_config.json`) and detects
   installed/running `cloudflared` and `turnserver` (coturn) daemons.
4. Supports an admin-toggleable `maintenance_offline_mode` so the PC-offline status page
   and Cloudflare edge fallback behavior can be verified locally and in automated tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional


class NetworkConfigManager:
    """Manages STUN/TURN ICE credentials, external domain settings, and offline simulation."""

    def __init__(self, data_root: Optional[Path] = None) -> None:
        project_root = Path(__file__).resolve().parent.parent
        self.data_root = (data_root or (project_root / "data")).resolve()
        self.config_path = self.data_root / "network_config.json"

        self.public_domain: str = os.environ.get("PUBLIC_DOMAIN", "").strip()
        self.cloudflare_tunnel_name: str = os.environ.get(
            "CLOUDFLARE_TUNNEL_NAME", "ryoku-cloud-gaming"
        ).strip()
        self.stun_url: str = os.environ.get(
            "STUN_URL", "stun:stun.l.google.com:19302"
        ).strip()
        self.turn_url: str = os.environ.get("TURN_URL", "").strip()
        self.turn_secret: str = os.environ.get("TURN_SECRET", "").strip()
        self.turn_username: str = os.environ.get("TURN_USERNAME", "").strip()
        self.turn_password: str = os.environ.get("TURN_PASSWORD", "").strip()
        self.turn_realm: str = os.environ.get("TURN_REALM", "ryoku.local").strip()
        self.turn_ttl_sec: int = int(os.environ.get("TURN_TTL_SEC", "86400"))
        self.enable_container_ice: bool = (
            os.environ.get("ENABLE_CONTAINER_ICE", "0").strip() == "1"
        )
        self.maintenance_offline_mode: bool = False

        self._load_persisted_config()

    def _load_persisted_config(self) -> None:
        if not self.config_path.exists():
            return
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.public_domain = str(raw.get("public_domain", self.public_domain)).strip()
                self.cloudflare_tunnel_name = str(
                    raw.get("cloudflare_tunnel_name", self.cloudflare_tunnel_name)
                ).strip()
                self.stun_url = str(raw.get("stun_url", self.stun_url)).strip()
                self.turn_url = str(raw.get("turn_url", self.turn_url)).strip()
                self.turn_secret = str(raw.get("turn_secret", self.turn_secret)).strip()
                self.turn_username = str(raw.get("turn_username", self.turn_username)).strip()
                self.turn_password = str(raw.get("turn_password", self.turn_password)).strip()
                self.turn_realm = str(raw.get("turn_realm", self.turn_realm)).strip()
                self.turn_ttl_sec = int(raw.get("turn_ttl_sec", self.turn_ttl_sec))
                self.enable_container_ice = bool(
                    raw.get("enable_container_ice", self.enable_container_ice)
                )
                self.maintenance_offline_mode = bool(
                    raw.get("maintenance_offline_mode", self.maintenance_offline_mode)
                )
        except Exception:
            pass

    def save_config(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "public_domain": self.public_domain,
            "cloudflare_tunnel_name": self.cloudflare_tunnel_name,
            "stun_url": self.stun_url,
            "turn_url": self.turn_url,
            "turn_secret": self.turn_secret,
            "turn_username": self.turn_username,
            "turn_password": self.turn_password,
            "turn_realm": self.turn_realm,
            "turn_ttl_sec": self.turn_ttl_sec,
            "enable_container_ice": self.enable_container_ice,
            "maintenance_offline_mode": self.maintenance_offline_mode,
        }
        self.config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def update_config(self, updates: Dict[str, object]) -> Dict[str, object]:
        if "public_domain" in updates and updates["public_domain"] is not None:
            dom = str(updates["public_domain"]).strip()
            dom = dom.removeprefix("https://").removeprefix("http://").rstrip("/")
            self.public_domain = dom
        if "cloudflare_tunnel_name" in updates and updates["cloudflare_tunnel_name"] is not None:
            self.cloudflare_tunnel_name = str(updates["cloudflare_tunnel_name"]).strip()
        if "stun_url" in updates and updates["stun_url"] is not None:
            self.stun_url = str(updates["stun_url"]).strip()
        if "turn_url" in updates and updates["turn_url"] is not None:
            self.turn_url = str(updates["turn_url"]).strip()
        if "turn_secret" in updates and updates["turn_secret"] is not None:
            self.turn_secret = str(updates["turn_secret"]).strip()
        if "turn_username" in updates and updates["turn_username"] is not None:
            self.turn_username = str(updates["turn_username"]).strip()
        if "turn_password" in updates and updates["turn_password"] is not None:
            self.turn_password = str(updates["turn_password"]).strip()
        if "turn_realm" in updates and updates["turn_realm"] is not None:
            self.turn_realm = str(updates["turn_realm"]).strip()
        if "turn_ttl_sec" in updates and updates["turn_ttl_sec"] is not None:
            self.turn_ttl_sec = max(60, int(updates["turn_ttl_sec"]))
        if "enable_container_ice" in updates and updates["enable_container_ice"] is not None:
            self.enable_container_ice = bool(updates["enable_container_ice"])
        if "maintenance_offline_mode" in updates and updates["maintenance_offline_mode"] is not None:
            self.maintenance_offline_mode = bool(updates["maintenance_offline_mode"])

        self.save_config()
        return self.get_network_status()

    def generate_turn_rest_credentials(self, username: str) -> Dict[str, object]:
        """
        Generate time-limited HMAC-SHA1 TURN REST API credentials compatible with coturn
        (`use-auth-secret` / `static-auth-secret`).
        """
        expires_at = int(time.time()) + self.turn_ttl_sec
        turn_user = f"{expires_at}:{username}"
        digest = hmac.new(
            self.turn_secret.encode("utf-8"),
            turn_user.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        credential = base64.b64encode(digest).decode("ascii")
        return {
            "username": turn_user,
            "credential": credential,
            "ttl_sec": self.turn_ttl_sec,
            "expires_at": expires_at,
        }

    def get_client_ice_config(self, username: str = "player") -> Dict[str, object]:
        """
        Build the browser `RTCPeerConnection` ICE configuration (`iceServers` list).
        """
        ice_servers: List[Dict[str, object]] = []
        if self.stun_url:
            stun_formatted = self.stun_url
            if stun_formatted.startswith("stun://"):
                stun_formatted = "stun:" + stun_formatted[len("stun://") :]
            ice_servers.append({"urls": [stun_formatted]})

        turn_mode = "disabled"
        turn_expires_at: Optional[int] = None

        if self.turn_url:
            turn_formatted = self.turn_url
            if turn_formatted.startswith("turn://"):
                turn_formatted = "turn:" + turn_formatted[len("turn://") :]
            elif turn_formatted.startswith("turns://"):
                turn_formatted = "turns:" + turn_formatted[len("turns://") :]

            if self.turn_secret:
                creds = self.generate_turn_rest_credentials(username)
                turn_mode = "hmac_rest"
                turn_expires_at = int(creds["expires_at"])
                ice_servers.append(
                    {
                        "urls": [turn_formatted],
                        "username": creds["username"],
                        "credential": creds["credential"],
                    }
                )
            elif self.turn_username and self.turn_password:
                turn_mode = "static"
                ice_servers.append(
                    {
                        "urls": [turn_formatted],
                        "username": self.turn_username,
                        "credential": self.turn_password,
                    }
                )
            else:
                turn_mode = "unauthenticated"
                ice_servers.append({"urls": [turn_formatted]})

        return {
            "ok": True,
            "iceServers": ice_servers,
            "iceTransportPolicy": "all",
            "turn_mode": turn_mode,
            "turn_expires_at": turn_expires_at,
            "public_domain": self.public_domain,
        }

    @staticmethod
    def format_gstreamer_stun_uri(stun_url: str) -> str:
        """Convert W3C `stun:host:port` into GStreamer `webrtcbin` `stun://host:port`."""
        clean = stun_url.strip()
        if not clean:
            return ""
        if clean.startswith("stun://"):
            return clean
        if clean.startswith("stun:"):
            return "stun://" + clean[len("stun:") :]
        return f"stun://{clean}"

    @staticmethod
    def format_gstreamer_turn_uri(
        turn_url: str, username: str = "", password: str = ""
    ) -> str:
        """
        Convert W3C `turn:host:port` + credentials into GStreamer `webrtcbin`
        `turn://user:pass@host:port` URI.
        """
        clean = turn_url.strip()
        if not clean:
            return ""
        scheme = "turns" if clean.startswith(("turns:", "turns://")) else "turn"
        host_part = (
            clean.removeprefix("turns://")
            .removeprefix("turn://")
            .removeprefix("turns:")
            .removeprefix("turn:")
        )
        if username and password:
            enc_u = urllib.parse.quote(username, safe="")
            enc_p = urllib.parse.quote(password, safe="")
            return f"{scheme}://{enc_u}:{enc_p}@{host_part}"
        return f"{scheme}://{host_part}"

    def get_gstreamer_ice_env(self, username: str = "player") -> Dict[str, str]:
        """
        Return environment variables (`STUN_SERVER`, `TURN_SERVER`) to pass into the
        isolated game container when container-side STUN/TURN traversal is enabled.
        """
        env: Dict[str, str] = {}
        if not self.enable_container_ice:
            return env

        if self.stun_url:
            env["STUN_SERVER"] = self.format_gstreamer_stun_uri(self.stun_url)

        if self.turn_url:
            if self.turn_secret:
                creds = self.generate_turn_rest_credentials(username)
                env["TURN_SERVER"] = self.format_gstreamer_turn_uri(
                    self.turn_url,
                    username=str(creds["username"]),
                    password=str(creds["credential"]),
                )
            elif self.turn_username and self.turn_password:
                env["TURN_SERVER"] = self.format_gstreamer_turn_uri(
                    self.turn_url,
                    username=self.turn_username,
                    password=self.turn_password,
                )
            else:
                env["TURN_SERVER"] = self.format_gstreamer_turn_uri(self.turn_url)
        return env

    @staticmethod
    def _is_process_running(proc_name: str) -> bool:
        try:
            res = subprocess.run(
                ["pgrep", "-x", proc_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=1.0,
            )
            return res.returncode == 0
        except Exception:
            return False

    def get_network_status(self) -> Dict[str, object]:
        """Return external access, Cloudflare Tunnel, and STUN/TURN status for Admin UI."""
        cloudflared_bin = shutil.which("cloudflared")
        turnserver_bin = shutil.which("turnserver")
        cloudflared_running = self._is_process_running("cloudflared")
        turnserver_running = self._is_process_running("turnserver")

        turn_configured = bool(self.turn_url and (self.turn_secret or self.turn_username))
        return {
            "public_domain": self.public_domain,
            "https_url": f"https://{self.public_domain}" if self.public_domain else "",
            "cloudflare_tunnel_name": self.cloudflare_tunnel_name,
            "cloudflared_installed": cloudflared_bin is not None,
            "cloudflared_running": cloudflared_running,
            "turnserver_installed": turnserver_bin is not None,
            "turnserver_running": turnserver_running,
            "stun_url": self.stun_url,
            "turn_url": self.turn_url,
            "turn_configured": turn_configured,
            "turn_has_secret": bool(self.turn_secret),
            "turn_username": self.turn_username,
            "turn_realm": self.turn_realm,
            "turn_ttl_sec": self.turn_ttl_sec,
            "enable_container_ice": self.enable_container_ice,
            "maintenance_offline_mode": self.maintenance_offline_mode,
        }

