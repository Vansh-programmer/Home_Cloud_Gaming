#!/usr/bin/env python3
"""
RYOKU CLOUD GAMING // NATIVE CLIENT APPLICATION
================================================
Dedicated native desktop client for Ryoku Cloud Gaming.
Exclusively uses Moonlight GameStream UDP for sub-2ms raw streaming.
Zero WebRTC. Zero browser fallback.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 1. Load PyGObject Gtk
try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GLib
except Exception as e:
    print(f"[ERROR] Could not load PyGObject Gtk: {e}")
    print("Please install python3-gobject via your package manager.")
    sys.exit(1)

# 2. Try WebKit2; if not present, will fall back to native GTK UI
HAS_WEBKIT = False
WebKit2 = None
for v in ["4.1", "4.0"]:
    try:
        gi.require_version("WebKit2", v)
        from gi.repository import WebKit2
        HAS_WEBKIT = True
        break
    except Exception:
        continue


class BaseRyokuClient:
    """Shared Moonlight streaming engine launcher and pairing manager."""
    server_url: str
    host_target: str
    moonlight_process: subprocess.Popen | None = None

    def _resolve_streaming_host(self) -> None:
        """Queries the Ryoku server to find the host's direct Tailscale WireGuard or LAN IP."""
        if self.host_target and not any(self.host_target.endswith(t) for t in (".online", ".com", ".net", ".org", ".io")) and self.host_target != "127.0.0.1":
            return
        try:
            req = urllib.request.Request(f"{self.server_url}/api/client/endpoint", headers={"User-Agent": "RyokuClient"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                rec = data.get("recommended_host")
                if rec and rec != "127.0.0.1":
                    print(f"[RYOKU CLIENT] Resolved direct streaming host: {rec}")
                    self.host_target = rec
        except Exception as e:
            print(f"[RYOKU CLIENT] Host resolution notice: {e}")

    def _get_moonlight_cmd(self) -> list[str]:
        if shutil.which("moonlight"):
            return [shutil.which("moonlight")]
        elif shutil.which("moonlight-qt"):
            return [shutil.which("moonlight-qt")]
        elif shutil.which("flatpak"):
            try:
                res = subprocess.run(
                    ["flatpak", "info", "com.moonlight_stream.Moonlight"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if res.returncode == 0:
                    return ["flatpak", "run", "com.moonlight_stream.Moonlight"]
            except Exception:
                pass
        return []

    def pair_with_host(self, pin: str | None = None) -> bool:
        """Pairs Moonlight client with Sunshine host using a 4-digit PIN."""
        moonlight_cmd = self._get_moonlight_cmd()
        if not moonlight_cmd:
            print("[RYOKU PAIR] Moonlight binary or Flatpak not found.")
            return False

        self._resolve_streaming_host()
        auto_pin = pin or f"{random.randint(1000, 9999)}"
        print(f"[RYOKU PAIR] Initiating pairing with host '{self.host_target}' using PIN {auto_pin}...")

        pair_cmd = moonlight_cmd + ["pair", self.host_target, "--pin", auto_pin]
        proc = subprocess.Popen(
            pair_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Give Moonlight 1s to open pairing socket with Sunshine
        time.sleep(1.0)

        # Submit PIN to Sunshine via Ryoku backend
        try:
            req = urllib.request.Request(
                f"{self.server_url}/api/client/pair",
                data=json.dumps({"pin": auto_pin}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                print(f"[RYOKU PAIR] Sunshine accepted PIN {auto_pin} (HTTP {resp.status})")
        except Exception as e:
            print(f"[RYOKU PAIR] Notice sending PIN to server: {e}")

        try:
            stdout, stderr = proc.communicate(timeout=6)
            out = (stdout or "") + (stderr or "")
            print(f"[RYOKU PAIR] Moonlight output:\n{out}")
            if "successfully paired" in out.lower() or proc.returncode == 0:
                print(f"[RYOKU PAIR] ✓ Host '{self.host_target}' successfully paired!")
                return True
        except Exception as e:
            print(f"[RYOKU PAIR] Pair wait notice: {e}")
            proc.kill()

        return False

    def _handle_moonlight_stream(self, opts: dict) -> None:
        """Invokes the native Moonlight streaming engine."""
        game_title = opts.get("title", "CyberArena 3D")
        app_id = str(opts.get("appId", "0"))
        width = int(opts.get("width", 1920))
        height = int(opts.get("height", 1080))
        fps = int(opts.get("fps", 120))
        bitrate = int(opts.get("bitrate", 35000))

        moonlight_cmd = self._get_moonlight_cmd()
        if not moonlight_cmd:
            self._show_moonlight_missing_dialog()
            return

        # Ensure direct IP
        self._resolve_streaming_host()

        print(f"[RYOKU MOONLIGHT] Launching native stream for '{game_title}' ({width}x{height} @ {fps}fps, {bitrate}kbps)...")
        print(f"[RYOKU MOONLIGHT] Target Host: {self.host_target}")

        cmd = moonlight_cmd + [
            "stream",
            self.host_target,
            game_title,
            "--resolution", f"{width}x{height}",
            "--fps", str(fps),
            "--bitrate", str(bitrate),
            "--quit-after",
        ]

        if hasattr(self, "hide"):
            self.hide()

        def run_proc():
            try:
                # 1. Attempt direct Moonlight stream (connects instantly if paired)
                print(f"[RYOKU MOONLIGHT] Connecting raw UDP stream to '{game_title}'...")
                proc = subprocess.Popen(cmd)
                self.moonlight_process = proc
                proc.wait()

                # 2. If stream exited immediately (not paired), auto-pair and retry
                if proc.returncode != 0:
                    print(f"[RYOKU MOONLIGHT] Stream exited ({proc.returncode}). Host not paired yet; pairing now...")
                    paired = self.pair_with_host()
                    if paired:
                        print(f"[RYOKU MOONLIGHT] Launching stream for '{game_title}' after pairing...")
                        proc = subprocess.Popen(cmd)
                        self.moonlight_process = proc
                        proc.wait()

            except Exception as err:
                print(f"[ERROR] Moonlight stream failed: {err}")
            finally:
                self.moonlight_process = None
                if hasattr(self, "_restore_client_window"):
                    GLib.idle_add(self._restore_client_window)

        t = threading.Thread(target=run_proc, daemon=True)
        t.start()

    def _show_moonlight_missing_dialog(self) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self if isinstance(self, Gtk.Window) else None,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text="Moonlight Engine Not Found"
        )
        dialog.format_secondary_text(
            "To play at 120 FPS sub-2ms, please install Moonlight on Fedora:\n\n"
            "flatpak install flathub com.moonlight_stream.Moonlight\n\n"
            "Or via DNF: sudo dnf install moonlight-qt"
        )
        dialog.run()
        dialog.destroy()


class RyokuClientWindow(Gtk.Window, BaseRyokuClient):
    """WebKit2-based live UI native client window."""
    def __init__(self, server_url: str, host_target: str) -> None:
        super().__init__(title="RYOKU // MOONLIGHT NATIVE CLIENT (120 FPS)")
        self.server_url = server_url.rstrip("/")
        self.host_target = host_target
        self.moonlight_process = None

        self.set_default_size(1280, 800)
        self.set_position(Gtk.WindowPosition.CENTER)

        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-application-prefer-dark-theme", True)

        self._resolve_streaming_host()

        # Define JS Bridge for Moonlight Handoff
        self.bridge_js = """
            (function() {
                window.ryokuIsNative = true;
                window.ryokuNative = {
                    isNative: true,
                    version: '2.0.0',
                    engine: 'moonlight-udp',
                    launchMoonlight: function(opts) {
                        try {
                            if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.ryokuNativeBridge) {
                                window.webkit.messageHandlers.ryokuNativeBridge.postMessage(JSON.stringify({
                                    action: 'launch_moonlight',
                                    opts: opts || {}
                                }));
                            }
                        } catch(err) {
                            console.error('Ryoku bridge error:', err);
                        }
                    },
                    notify: function(msg) {
                        try {
                            if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.ryokuNativeBridge) {
                                window.webkit.messageHandlers.ryokuNativeBridge.postMessage(JSON.stringify({
                                    action: 'notify',
                                    message: msg
                                }));
                            }
                        } catch(e) {}
                    }
                };
                try {
                    sessionStorage.setItem('ryoku_native_engine', 'moonlight');
                    localStorage.setItem('ryoku_engine', 'moonlight');
                } catch(e) {}
                console.log('[RYOKU NATIVE] Moonlight UDP Bridge Injected successfully.');
                var badge = document.getElementById('native-engine-badge');
                if (badge) badge.style.display = 'inline-block';
            })();
        """

        # Set up WebKit User Content Manager for JS -> Python bridge
        self.user_content_mgr = WebKit2.UserContentManager()
        self.user_content_mgr.register_script_message_handler("ryokuNativeBridge")
        self.user_content_mgr.connect("script-message-received::ryokuNativeBridge", self._on_js_message)

        # Inject native identification script
        try:
            init_script = WebKit2.UserScript(
                source=self.bridge_js,
                injected_frames=WebKit2.UserContentInjectedFrames.ALL_FRAMES,
                injection_time=WebKit2.UserScriptInjectionTime.START,
                allow_list=None,
                block_list=None
            )
        except TypeError:
            try:
                init_script = WebKit2.UserScript(
                    self.bridge_js,
                    WebKit2.UserContentInjectedFrames.ALL_FRAMES,
                    WebKit2.UserScriptInjectionTime.START,
                    None,
                    None
                )
            except Exception:
                init_script = WebKit2.UserScript.new(
                    self.bridge_js,
                    WebKit2.UserContentInjectedFrames.ALL_FRAMES,
                    WebKit2.UserScriptInjectionTime.START
                )
        self.user_content_mgr.add_script(init_script)

        # Create WebKit WebView
        self.webview = WebKit2.WebView.new_with_user_content_manager(self.user_content_mgr)

        settings_web = self.webview.get_settings()
        if settings_web:
            settings_web.set_enable_webgl(True)
            settings_web.set_enable_accelerated_2d_canvas(True)
            settings_web.set_enable_developer_extras(True)
            settings_web.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)
            ua = settings_web.get_user_agent() or ""
            settings_web.set_user_agent(f"{ua} RyokuNativeClient/2.0")
            self.webview.set_settings(settings_web)

        self.webview.connect("load-changed", self._on_load_changed)

        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.webview)
        self.add(scrolled)

        self.connect("destroy", self._on_window_close)

        print(f"[RYOKU CLIENT] Loading interface from: {self.server_url}")
        print(f"[RYOKU CLIENT] Moonlight Target Host: {self.host_target}")
        self.webview.load_uri(self.server_url)

    def _on_load_changed(self, webview, load_event) -> None:
        if load_event in (WebKit2.LoadEvent.COMMITTED, WebKit2.LoadEvent.FINISHED):
            try:
                webview.run_javascript(self.bridge_js, None, None, None)
            except Exception:
                pass

    def _on_js_message(self, _content_mgr, js_result) -> None:
        """Handle messages received from the Ryoku UI."""
        try:
            # Modern WebKit2 uses get_js_value() returning JavaScriptCore.Value
            if hasattr(js_result, "get_js_value"):
                val = js_result.get_js_value()
            elif hasattr(js_result, "get_value"):
                val = js_result.get_value()
            else:
                val = js_result

            if hasattr(val, "is_string") and val.is_string():
                raw = val.to_string()
            elif hasattr(val, "to_json"):
                raw = val.to_json(0)
            elif hasattr(val, "to_string"):
                raw = val.to_string()
            else:
                raw = str(val)

            if isinstance(raw, dict):
                data = raw
            else:
                data = json.loads(raw)

            action = data.get("action")
            if action == "launch_moonlight":
                opts = data.get("opts", {})
                self._handle_moonlight_stream(opts)
            elif action == "notify":
                print(f"[RYOKU UI] {data.get('message')}")
        except Exception as e:
            print(f"[ERROR] Failed to process JS message: {e}")

    def _restore_client_window(self) -> None:
        self.show_all()
        self.present()
        print("[RYOKU MOONLIGHT] Stream session finished. Restored Ryoku UI.")

    def _on_window_close(self, _widget) -> None:
        if self.moonlight_process:
            try:
                self.moonlight_process.terminate()
            except Exception:
                pass
        Gtk.main_quit()


class RyokuNativeGTKWindow(Gtk.Window, BaseRyokuClient):
    """Pure GTK3 fallback window if WebKit2 is not installed on system."""
    def __init__(self, server_url: str, host_target: str) -> None:
        super().__init__(title="RYOKU // MOONLIGHT 120 FPS NATIVE LAUNCHER")
        self.server_url = server_url.rstrip("/")
        self.host_target = host_target
        self.moonlight_process = None

        self.set_default_size(900, 600)
        self.set_position(Gtk.WindowPosition.CENTER)

        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-application-prefer-dark-theme", True)

        self._resolve_streaming_host()

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        main_box.set_border_width(24)

        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        emblem = Gtk.Label()
        emblem.set_markup("<span font='18' weight='heavy' foreground='#c8ff00'>⚡ RYOKU</span>")
        header_box.pack_start(emblem, False, False, 0)

        sub_label = Gtk.Label()
        sub_label.set_markup(
            f"<span font='11' foreground='#94a3b8'>Native Moonlight 120 FPS • Host: <span foreground='#c8ff00' weight='bold'>{self.host_target}</span></span>"
        )
        header_box.pack_start(sub_label, False, False, 0)
        main_box.pack_start(header_box, False, False, 0)

        # Games list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)

        games = self._fetch_games()
        for g in games:
            row = Gtk.ListBoxRow()
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            row_box.set_border_width(12)

            title_label = Gtk.Label(xalign=0)
            title_label.set_markup(f"<span font='13' weight='bold' foreground='#ffffff'>{g['title']}</span>")
            row_box.pack_start(title_label, True, True, 0)

            play_btn = Gtk.Button()
            play_btn.set_label("▶ Play (120 FPS)")
            play_btn.connect("clicked", lambda _, title=g['title']: self._handle_moonlight_stream({"title": title}))
            row_box.pack_end(play_btn, False, False, 0)

            row.add(row_box)
            list_box.add(row)

        scrolled.add(list_box)
        main_box.pack_start(scrolled, True, True, 0)

        self.add(main_box)
        self.connect("destroy", self._on_window_close)

    def _fetch_games(self) -> list[dict]:
        try:
            req = urllib.request.Request(f"{self.server_url}/api/library", headers={"User-Agent": "RyokuClient"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok") and data.get("games"):
                    return [{"title": x.get("title", "Game")} for x in data["games"]]
        except Exception:
            pass
        return [
            {"title": "CyberArena 3D"},
            {"title": "Steam Big Picture"},
            {"title": "Heroic Games Launcher (Epic & GOG)"},
            {"title": "Lethal Company (Co-op 4P LAN)"},
            {"title": "Tomb Raider"},
            {"title": "Rise of the Tomb Raider"},
        ]

    def _restore_client_window(self) -> None:
        self.show_all()
        self.present()

    def _on_window_close(self, _widget) -> None:
        if self.moonlight_process:
            try:
                self.moonlight_process.terminate()
            except Exception:
                pass
        Gtk.main_quit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ryoku Cloud Gaming Native Client")
    parser.add_argument(
        "--server",
        default="https://play.vanshdev.online",
        help="Ryoku Web Server URL"
    )
    parser.add_argument(
        "--host",
        default="100.89.198.41",
        help="Target streaming PC address for Moonlight UDP (IP, Tailscale IP, or domain)"
    )
    parser.add_argument(
        "--pair",
        action="store_true",
        help="Pair Moonlight with the Sunshine host using automatic 4-digit PIN exchange"
    )
    args = parser.parse_args()

    if args.pair:
        client = BaseRyokuClient()
        client.server_url = args.server.rstrip("/")
        client.host_target = args.host
        success = client.pair_with_host()
        sys.exit(0 if success else 1)

    if HAS_WEBKIT:
        app = RyokuClientWindow(server_url=args.server, host_target=args.host)
    else:
        print("[RYOKU] WebKit2 not available. Launching pure native GTK3 Moonlight launcher...")
        app = RyokuNativeGTKWindow(server_url=args.server, host_target=args.host)

    app.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
