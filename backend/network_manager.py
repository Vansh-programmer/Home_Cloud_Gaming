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
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

CLOUDFLARE_TURN_API = "https://rtc.live.cloudflare.com/v1/turn/keys/{key_id}/credentials/generate-ice-servers"


class NetworkConfigManager:
    """Manages STUN/TURN ICE credentials, external domain settings, and offline simulation."""

    def __init__(self, data_root: Optional[Path] = None) -> None:
        project_root = Path(__file__).resolve().parent.parent
        default_data_root = (project_root / "data").resolve()
        self.data_root = (data_root or default_data_root).resolve()
        self.config_path = self.data_root / "network_config.json"

        if self.data_root == default_data_root:
            self._load_dotenv(project_root / ".env")

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
            # Default ON: without a STUN server the host-side GStreamer webrtcbin only
            # advertises private LAN candidates, so remote (internet) browsers can never
            # establish the UDP media path (black screen while the website still works).
            os.environ.get("ENABLE_CONTAINER_ICE", "1").strip() == "1"
        )
        # Cloudflare Realtime TURN (free managed relay): lets players on ANY outside
        # network (mobile data, CGNAT, strict firewalls) receive the UDP/TCP media stream
        # without opening router ports. Keys come from the Cloudflare dashboard.
        self.cf_turn_key_id: str = os.environ.get("CF_TURN_KEY_ID", "").strip()
        self.cf_turn_api_token: str = os.environ.get("CF_TURN_API_TOKEN", "").strip()
        self.maintenance_offline_mode: bool = False

        self._cf_cache_lock = threading.Lock()
        self._cf_cache: Optional[Dict[str, object]] = None
        self._cf_cache_expiry: float = 0.0
        self._cf_last_error: str = ""

        self._load_persisted_config()

    @staticmethod
    def _load_dotenv(dotenv_path: Path) -> None:
        """Load key=value pairs from .env into os.environ if not already set."""
        if not dotenv_path.exists():
            return
        try:
            for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        except Exception:
            pass

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

                # Empty saved values must never override real values from .env / environment
                def _saved(key: str, current: str) -> str:
                    val = str(raw.get(key, "") or "").strip()
                    return val if val else current

                self.turn_url = _saved("turn_url", self.turn_url)
                self.turn_secret = _saved("turn_secret", self.turn_secret)
                self.turn_username = _saved("turn_username", self.turn_username)
                self.turn_password = _saved("turn_password", self.turn_password)
                self.turn_realm = str(raw.get("turn_realm", self.turn_realm)).strip()
                self.turn_ttl_sec = int(raw.get("turn_ttl_sec", self.turn_ttl_sec))
                self.enable_container_ice = bool(
                    raw.get("enable_container_ice", self.enable_container_ice)
                )
                self.maintenance_offline_mode = bool(
                    raw.get("maintenance_offline_mode", self.maintenance_offline_mode)
                )
                self.cf_turn_key_id = _saved("cf_turn_key_id", self.cf_turn_key_id)
                self.cf_turn_api_token = _saved("cf_turn_api_token", self.cf_turn_api_token)
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
            "cf_turn_key_id": self.cf_turn_key_id,
            "cf_turn_api_token": self.cf_turn_api_token,
        }
        self.config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(self.config_path, 0o600)
        except OSError:
            pass

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
        if "cf_turn_key_id" in updates and updates["cf_turn_key_id"] is not None:
            self.cf_turn_key_id = str(updates["cf_turn_key_id"]).strip()
            self._cf_cache = None
        if "cf_turn_api_token" in updates and updates["cf_turn_api_token"] is not None:
            self.cf_turn_api_token = str(updates["cf_turn_api_token"]).strip()
            self._cf_cache = None

        self.save_config()
        return self.get_network_status()

    def generate_turn_rest_credentials(self, username: str) -> Dict[str, object]:
        """
        Generate time-limited HMAC-SHA1 TURN REST API credentials compatible with coturn
        (`use-auth-secret` / `static-auth-secret`).
        """
        expires_at = int(time.time()) + self.turn_ttl_sec
        for _ in range(16):
            turn_user = f"{expires_at}:{username}"
            digest = hmac.new(
                self.turn_secret.encode("utf-8"),
                turn_user.encode("utf-8"),
                hashlib.sha1,
            ).digest()
            credential = base64.b64encode(digest).decode("ascii")
            if "/" not in credential:
                break
            expires_at += 1
        return {
            "username": turn_user,
            "credential": credential,
            "ttl_sec": self.turn_ttl_sec,
            "expires_at": expires_at,
        }

    @property
    def cloudflare_turn_configured(self) -> bool:
        return bool(self.cf_turn_key_id and self.cf_turn_api_token)

    def fetch_cloudflare_ice_servers(self, force: bool = False) -> List[Dict[str, object]]:
        """
        Fetch short-lived STUN/TURN credentials from Cloudflare Realtime TURN
        (`generate-ice-servers`). Results are cached for ~1h less than their TTL so every
        browser ICE request and every new game session reuses a valid credential.
        Returns an empty list (and records `_cf_last_error`) if the API is unreachable.
        """
        if not self.cloudflare_turn_configured:
            return []
        with self._cf_cache_lock:
            now = time.time()
            if not force and self._cf_cache and now < self._cf_cache_expiry:
                return list(self._cf_cache.get("iceServers", []))  # type: ignore[arg-type]

            ttl = max(3600, int(self.turn_ttl_sec))
            url = CLOUDFLARE_TURN_API.format(key_id=urllib.parse.quote(self.cf_turn_key_id, safe=""))
            req = urllib.request.Request(
                url,
                data=json.dumps({"ttl": ttl}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.cf_turn_api_token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=6.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                servers = data.get("iceServers")
                if isinstance(servers, dict):
                    servers = [servers]
                if not isinstance(servers, list) or not servers:
                    raise ValueError("Cloudflare TURN response did not contain iceServers")
                self._cf_cache = {"iceServers": servers}
                self._cf_cache_expiry = now + max(300, ttl - 3600)
                self._cf_last_error = ""
                return list(servers)
            except urllib.error.HTTPError as exc:
                self._cf_last_error = f"Cloudflare TURN API HTTP {exc.code} (check Key ID / API Token)"
            except Exception as exc:  # noqa: BLE001
                self._cf_last_error = f"Cloudflare TURN API unreachable: {exc}"
            # Serve a stale-but-possibly-valid cache rather than nothing
            if self._cf_cache:
                return list(self._cf_cache.get("iceServers", []))  # type: ignore[arg-type]
            return []

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

        cf_servers = self.fetch_cloudflare_ice_servers()
        if cf_servers:
            ice_servers.extend(cf_servers)
            turn_mode = "cloudflare"
            turn_expires_at = int(self._cf_cache_expiry) if self._cf_cache_expiry else None

        if self.turn_url:
            turn_urls = self.parse_turn_urls(self.turn_url)

            if self.turn_username and self.turn_password:
                # Static provider credentials (Metered / ExpressTURN) always win
                turn_mode = "static"
                ice_servers.append(
                    {
                        "urls": turn_urls,
                        "username": self.turn_username,
                        "credential": self.turn_password,
                    }
                )
            elif self.turn_secret:
                creds = self.generate_turn_rest_credentials(username)
                turn_mode = "hmac_rest"
                turn_expires_at = int(creds["expires_at"])
                ice_servers.append(
                    {
                        "urls": turn_urls,
                        "username": creds["username"],
                        "credential": creds["credential"],
                    }
                )
            else:
                turn_mode = "unauthenticated"
                ice_servers.append({"urls": turn_urls})

        return {
            "ok": True,
            "iceServers": ice_servers,
            "iceTransportPolicy": "all",
            "turn_mode": turn_mode,
            "turn_expires_at": turn_expires_at,
            "turn_error": self._cf_last_error,
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
    def parse_turn_urls(raw: str) -> List[str]:
        """
        Split a comma/space/newline separated list of TURN URLs and normalise
        `turn://host` -> `turn:host` (W3C form). Free providers (Metered, ExpressTURN, ...)
        give several URLs (udp 3478, tcp 80, tls 443) that should all be offered.

        A bare `host:port` (no scheme, as copied from many provider dashboards) is
        auto-fixed to `turn:host:port` (UDP) plus a `?transport=tcp` twin so strict
        networks that block UDP can still reach the relay. Without a scheme the browser
        rejects the ICE server and no video connection can start at all.
        """
        urls: List[str] = []
        for part in raw.replace(",", " ").split():
            clean = part.strip()
            if not clean:
                continue
            if clean.startswith("turn://"):
                clean = "turn:" + clean[len("turn://") :]
            elif clean.startswith("turns://"):
                clean = "turns:" + clean[len("turns://") :]
            elif not clean.startswith(("turn:", "turns:", "stun:", "stuns:")):
                bare = clean.removeprefix("//")
                urls.append(f"turn:{bare}")
                if "transport=" not in bare:
                    sep = "&" if "?" in bare else "?"
                    urls.append(f"turn:{bare}{sep}transport=tcp")
                continue
            urls.append(clean)
        return urls

    @staticmethod
    def pick_preferred_turn_url(urls: List[str]) -> str:
        """Pick the lowest-latency relay URL for GStreamer (single URI): UDP, then TCP, then TLS."""
        if not urls:
            return ""
        for u in urls:
            if u.startswith("turn:") and "transport=tcp" not in u:
                return u
        for u in urls:
            if u.startswith("turn:"):
                return u
        return urls[0]

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
            # GStreamer webrtcbin parses turn-server via gst_uri_from_string_escaped,
            # which escapes '%' into '%25'. Therefore '=', '+', and ':' in passwords
            # or base64 keys MUST NOT be percent-encoded here, otherwise '%3D' becomes
            # '%253D', breaking authentication on providers like ExpressTURN / coturn.
            enc_u = urllib.parse.quote(username, safe="=+:!$&'()*+,;-._~")
            enc_p = urllib.parse.quote(password, safe="=+:!$&'()*+,;-._~")
            return f"{scheme}://{enc_u}:{enc_p}@{host_part}"
        return f"{scheme}://{host_part}"

    def _cloudflare_gstreamer_turn_uris(self) -> List[str]:
        """Build GStreamer turn URIs from Cloudflare credentials (both UDP and TCP)."""
        uris: List[str] = []
        for server in self.fetch_cloudflare_ice_servers():
            username = str(server.get("username", ""))
            credential = str(server.get("credential", ""))
            urls = server.get("urls", [])
            if isinstance(urls, str):
                urls = [urls]
            if not username or not credential or not isinstance(urls, list):
                continue
            for u in urls:
                if str(u).startswith(("turn:", "turns:")):
                    uris.append(self.format_gstreamer_turn_uri(str(u), username=username, password=credential))
        return uris

    def _cloudflare_gstreamer_turn_uri(self) -> str:
        """Build a primary GStreamer turn URI from Cloudflare creds."""
        uris = self._cloudflare_gstreamer_turn_uris()
        if not uris:
            return ""
        # Prefer UDP relay for lowest latency
        return next((u for u in uris if "transport=udp" in u or "transport=" not in u), uris[0])

    def get_gstreamer_ice_env(self, username: str = "player") -> Dict[str, str]:
        """
        Return environment variables (`STUN_SERVER`, `TURN_SERVER`, `TURN_SERVERS`) to pass
        into the isolated game container when container-side STUN/TURN traversal is enabled.
        `TURN_SERVERS` is a comma-separated list of all available relays (UDP + TCP).
        """
        env: Dict[str, str] = {}
        if not self.enable_container_ice:
            return env

        if self.stun_url:
            env["STUN_SERVER"] = self.format_gstreamer_stun_uri(self.stun_url)

        # Preferred: Cloudflare Realtime TURN relay (works behind CGNAT / no port-forwarding)
        cf_turn_uris = self._cloudflare_gstreamer_turn_uris()
        if cf_turn_uris:
            env["TURN_SERVER"] = self._cloudflare_gstreamer_turn_uri()
            env["TURN_SERVERS"] = ",".join(cf_turn_uris)
            return env

        if self.turn_url:
            parsed_urls = self.parse_turn_urls(self.turn_url)
            all_turn_uris: List[str] = []
            if self.turn_username and self.turn_password:
                for u in parsed_urls:
                    all_turn_uris.append(
                        self.format_gstreamer_turn_uri(
                            u, username=self.turn_username, password=self.turn_password
                        )
                    )
            elif self.turn_secret:
                creds = self.generate_turn_rest_credentials(username)
                for u in parsed_urls:
                    all_turn_uris.append(
                        self.format_gstreamer_turn_uri(
                            u,
                            username=str(creds["username"]),
                            password=str(creds["credential"]),
                        )
                    )
            else:
                for u in parsed_urls:
                    all_turn_uris.append(self.format_gstreamer_turn_uri(u))

            if all_turn_uris:
                chosen_url = self.pick_preferred_turn_url(parsed_urls)
                # Primary single URI
                primary_uri = next(
                    (u for u in all_turn_uris if chosen_url in u), all_turn_uris[0]
                )
                env["TURN_SERVER"] = primary_uri
                env["TURN_SERVERS"] = ",".join(all_turn_uris)
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

        turn_configured = bool(
            (self.turn_url and (self.turn_secret or self.turn_username))
            or self.cloudflare_turn_configured
        )
        return {
            "public_domain": self.public_domain,
            "https_url": f"https://{self.public_domain}" if self.public_domain else "",
            "cloudflare_tunnel_name": self.cloudflare_tunnel_name,
            "cloudflared_installed": cloudflared_bin is not None,
            "cloudflared_running": cloudflared_running,
            "turnserver_installed": turnserver_bin is not None,
            "turnserver_running": turnserver_running,
            "cloudflare_turn_configured": self.cloudflare_turn_configured,
            "cloudflare_turn_error": self._cf_last_error,
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

