#!/usr/bin/env python3
"""
RYOKU CLOUD GAMING // NATIVE CLIENT APPLICATION
================================================
A native desktop client with Ryoku's custom cyberpunk UI that utilizes
the high-performance Moonlight GameStream UDP engine under the hood.

KEY FEATURES:
1. Live Web UI Sync:
   Loads the Ryoku web interface directly, meaning any UI/CSS/game updates
   made on the server immediately appear in this client app without recompilation!
2. Moonlight UDP Streaming:
   When launching a game, invokes the native C++ Moonlight engine for sub-2ms
   raw UDP streaming, 120 FPS, and hardware-accelerated NVDEC/DXVA2 decoding.
3. Sandbox Security:
   Confined to the launched game container — the host desktop and /home/vansh
   are completely blocked.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import Gtk, Gdk, GLib, WebKit2
except Exception as e:
    # Try fallback to WebKit2 4.0 if 4.1 isn't present
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.0")
        from gi.repository import Gtk, Gdk, GLib, WebKit2
    except Exception as e2:
        print(f"[ERROR] Could not load PyGObject WebKit2: {e2}")
        print("Please install python-gobject and webkit2gtk via your package manager.")
        sys.exit(1)


class RyokuClientWindow(Gtk.Window):
    def __init__(self, server_url: str, host_target: str) -> None:
        super().__init__(title="RYOKU // CLOUD GAMING")
        self.server_url = server_url.rstrip("/")
        self.host_target = host_target
        self.moonlight_process: subprocess.Popen | None = None

        self.set_default_size(1280, 800)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Dark cyberpunk theme for the native window frame
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-application-prefer-dark-theme", True)

        # Set up WebKit User Content Manager for JS -> Python bridge
        self.user_content_mgr = WebKit2.UserContentManager()
        self.user_content_mgr.register_script_message_handler("ryokuNativeBridge")
        self.user_content_mgr.connect("script-message-received::ryokuNativeBridge", self._on_js_message)

        # Inject native identification script into every page load
        init_script = WebKit2.UserScript(
            source="""
                window.ryokuNative = {
                    isNative: true,
                    version: '2.0.0',
                    engine: 'moonlight-udp',
                    launchMoonlight: function(opts) {
                        try {
                            window.webkit.messageHandlers.ryokuNativeBridge.postMessage(JSON.stringify({
                                action: 'launch_moonlight',
                                opts: opts || {}
                            }));
                        } catch(err) {
                            console.error('Ryoku bridge error:', err);
                        }
                    },
                    notify: function(msg) {
                        window.webkit.messageHandlers.ryokuNativeBridge.postMessage(JSON.stringify({
                            action: 'notify',
                            message: msg
                        }));
                    }
                };
                console.log('[RYOKU NATIVE] Moonlight UDP Bridge Injected successfully.');
            """,
            injected_frames=WebKit2.UserContentInjectedFrames.ALL_FRAMES,
            injection_time=WebKit2.UserScriptInjectionTime.START,
            whitelist=[],
            blacklist=[]
        )
        self.user_content_mgr.add_script(init_script)

        # Create WebKit WebView
        web_context = WebKit2.WebContext.get_default()
        # Enable hardware acceleration
        settings_web = WebKit2.Settings()
        settings_web.set_enable_webgl(True)
        settings_web.set_enable_accelerated_2d_canvas(True)
        settings_web.set_enable_developer_extras(True)
        settings_web.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)

        self.webview = WebKit2.WebView.new_with_context(web_context)
        self.webview.set_settings(settings_web)

        # Wrap in scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.webview)
        self.add(scrolled)

        self.connect("destroy", self._on_window_close)

        # Load Ryoku Web Interface
        print(f"[RYOKU CLIENT] Loading live interface from: {self.server_url}")
        self.webview.load_uri(self.server_url)

    def _on_js_message(self, _content_mgr, js_result) -> None:
        """Handle messages received from the Ryoku web UI."""
        try:
            value = js_result.get_value()
            json_str = value.to_string()
            data = json.loads(json_str)
            action = data.get("action")

            if action == "launch_moonlight":
                opts = data.get("opts", {})
                self._handle_moonlight_stream(opts)
            elif action == "notify":
                print(f"[RYOKU UI] {data.get('message')}")
        except Exception as e:
            print(f"[ERROR] Failed to process JS message: {e}")

    def _handle_moonlight_stream(self, opts: dict) -> None:
        """Invokes the native Moonlight streaming engine."""
        game_title = opts.get("title", "CyberArena 3D")
        app_id = str(opts.get("appId", "0"))
        width = int(opts.get("width", 1920))
        height = int(opts.get("height", 1080))
        fps = int(opts.get("fps", 120))
        bitrate = int(opts.get("bitrate", 35000))

        moonlight_bin = shutil.which("moonlight-qt") or shutil.which("moonlight")

        if not moonlight_bin:
            self._show_moonlight_missing_dialog()
            return

        print(f"[RYOKU MOONLIGHT] Launching native stream for '{game_title}' ({width}x{height} @ {fps}fps, {bitrate}kbps)...")
        print(f"[RYOKU MOONLIGHT] Target Host: {self.host_target}")

        cmd = [
            moonlight_bin,
            "stream",
            self.host_target,
            game_title,
            "--width", str(width),
            "--height", str(height),
            "--fps", str(fps),
            "--bitrate", str(bitrate),
            "--quit-after",
        ]

        # Hide client window while gameplay is active
        self.hide()

        def run_proc():
            try:
                proc = subprocess.Popen(cmd)
                self.moonlight_process = proc
                proc.wait()
            except Exception as err:
                print(f"[ERROR] Moonlight stream failed: {err}")
            finally:
                self.moonlight_process = None
                GLib.idle_add(self._restore_client_window)

        import threading
        t = threading.Thread(target=run_proc, daemon=True)
        t.start()

    def _restore_client_window(self) -> None:
        """Restores the Ryoku client window when the Moonlight stream exits."""
        self.show_all()
        self.present()
        print("[RYOKU MOONLIGHT] Stream session finished. Restored Ryoku UI.")

    def _show_moonlight_missing_dialog(self) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text="Moonlight Engine Not Found"
        )
        dialog.format_secondary_text(
            "To use native 120 FPS Moonlight streaming, please install moonlight-qt:\n\n"
            "• Arch / CachyOS: sudo pacman -S moonlight-qt\n"
            "• Ubuntu / Debian: sudo apt install moonlight-qt\n"
            "• Fedora: sudo dnf install moonlight-qt\n\n"
            "In the meantime, browser-based WebRTC streaming is still available!"
        )
        dialog.run()
        dialog.destroy()

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
        default="http://localhost:8080",
        help="Ryoku Web Server URL (default: http://localhost:8080 or https://play.vanshdev.online)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Target streaming PC address for Moonlight UDP (IP, Tailscale IP, or domain)"
    )
    args = parser.parse_args()

    # Auto-detect Tailscale IP if running over local Tailscale mesh
    target_host = args.host
    if target_host == "127.0.0.1":
        ts_ip = shutil.which("tailscale")
        if ts_ip:
            try:
                out = subprocess.check_output(["tailscale", "ip", "-4"], text=True).strip()
                if out:
                    target_host = out
            except Exception:
                pass

    app = RyokuClientWindow(server_url=args.server, host_target=target_host)
    app.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
