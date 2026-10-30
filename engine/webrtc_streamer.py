"""
Hardware-Accelerated GStreamer WebRTC Streamer (NVENC H.264 + Opus Audio + RTCDataChannel).

Captures video strictly from the isolated session's Xwayland display (ximagesrc)
and audio strictly from the isolated PipeWire-Pulse virtual null-sink (pulsesrc),
encoding on the NVIDIA RTX 4060 via nvh264enc (low-latency-hq, zerolatency=true).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable, Dict, Optional

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstWebRTC", "1.0")
gi.require_version("GstSdp", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import GLib, Gst, GstSdp, GstVideo, GstWebRTC  # noqa: E402

Gst.init(None)

logger = logging.getLogger("webrtc_streamer")

QUALITY_PRESETS: Dict[str, Dict[str, int]] = {
    "low": {"bitrate_kbps": 3500, "fps": 60, "label": "Low (3.5 Mbps)"},
    "remote": {"bitrate_kbps": 6000, "fps": 60, "label": "Remote Smooth (6 Mbps)"},
    "medium": {"bitrate_kbps": 8500, "fps": 60, "label": "Medium (8.5 Mbps)"},
    "high": {"bitrate_kbps": 15000, "fps": 60, "label": "High LAN (15 Mbps)"},
    "ultra": {"bitrate_kbps": 25000, "fps": 60, "label": "Ultra Direct (25 Mbps)"},
}


class WebRTCPeerStream:
    """
    Manages a live GStreamer webrtcbin pipeline for a connected browser peer.
    Handles SDP Offer creation, Answer processing, ICE candidate exchange,
    RTCDataChannel low-latency input events, and live NVENC bitrate changes.
    """

    def __init__(
        self,
        display_name: str,
        pulse_source: str,
        width: int,
        height: int,
        fps: int,
        quality: str,
        on_signaling_message: Callable[[dict], None],
        on_input_event: Callable[[dict], None],
        stun_server: Optional[str] = None,
        turn_server: Optional[str] = None,
        audio_enabled: bool = True,
    ) -> None:
        self.display_name = display_name
        self.pulse_source = pulse_source
        self.width = width
        self.height = height
        self.fps = fps
        self.quality = quality if quality in QUALITY_PRESETS else "high"
        self.on_signaling_message = on_signaling_message
        self.on_input_event = on_input_event
        self.stun_server = (
            stun_server if stun_server is not None else os.environ.get("STUN_SERVER", "")
        )
        self.turn_server = (
            turn_server if turn_server is not None else (os.environ.get("TURN_SERVER", "") or None)
        )
        self.turn_servers: List[str] = []
        raw_servers = os.environ.get("TURN_SERVERS", "").strip()
        if raw_servers:
            self.turn_servers = [s.strip() for s in raw_servers.split(",") if s.strip()]
        elif self.turn_server:
            self.turn_servers = [self.turn_server]
        self.audio_enabled = audio_enabled

        self.pipe: Optional[Gst.Pipeline] = None
        self.webrtc: Optional[Gst.Element] = None
        self.venc: Optional[Gst.Element] = None
        self.data_channel: Optional[object] = None
        self._last_keyframe_time: float = 0.0
        self._negotiated = False
        self._remote_desc_set = False
        self._pending_ice: List[tuple[int, str]] = []
        self._lock = threading.Lock()

    def build_pipeline_description(self) -> str:
        preset = QUALITY_PRESETS.get(self.quality, QUALITY_PRESETS["remote"])
        bitrate_kbps = preset["bitrate_kbps"]
        target_fps = min(self.fps, preset["fps"])
        # Fast GOP size (1.0s max) guarantees rapid packet-loss recovery on outer networks
        gop_size = max(15, target_fps)
        vbv_kbits = max(300, bitrate_kbps // 30)

        stun_prop = f'stun-server="{self.stun_server}"' if self.stun_server else ""
        turn_prop = f'turn-server="{self.turn_server}"' if self.turn_server else ""

        if Gst.ElementFactory.find("nvh264enc") is not None:
            encoder_elem = (
                f"nvh264enc name=venc preset=p1 tune=ultra-low-latency zerolatency=true rc-mode=cbr "
                f"aud=true repeat-sequence-header=true bitrate={bitrate_kbps} gop-size={gop_size} bframes=0 "
                f"vbv-buffer-size={vbv_kbits} "
            )
        elif Gst.ElementFactory.find("vaapih264enc") is not None:
            logger.info("Using VA-API Hardware H.264 Encoder (Intel/AMD)")
            encoder_elem = (
                f"vaapih264enc name=venc rate-control=cbr tune=low-power "
                f"bitrate={bitrate_kbps} keyframe-period={gop_size} b-frames=0 "
            )
        elif Gst.ElementFactory.find("vah264enc") is not None:
            logger.info("Using Modern VA-API H.264 Encoder (Intel/AMD)")
            encoder_elem = (
                f"vah264enc name=venc rate-control=cbr "
                f"bitrate={bitrate_kbps} gop-size={gop_size} b-frames=0 "
            )
        else:
            logger.warning("No hardware H.264 encoder found (nvh264enc/vaapi); falling back to CPU x264enc")
            encoder_elem = (
                f"x264enc name=venc tune=zerolatency speed-preset=ultrafast "
                f"bitrate={bitrate_kbps} key-int-max={gop_size} bframes=0 "
            )

        video_branch = (
            f'ximagesrc display-name="{self.display_name}" use-damage=0 show-pointer=1 do-timestamp=true '
            f"! video/x-raw,framerate={target_fps}/1 "
            f"! queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream "
            f"! videoconvert n-threads=4 "
            f"! {encoder_elem}"
            f"! video/x-h264,profile=constrained-baseline,stream-format=byte-stream "
            f"! h264parse config-interval=-1 "
            f"! rtph264pay config-interval=-1 aggregate-mode=zero-latency mtu=1200 pt=96 "
            f"! queue name=net_video_queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream "
            f"! application/x-rtp,media=video,encoding-name=H264,payload=96 ! wb. "
        )

        if self.audio_enabled and self.pulse_source:
            audio_branch = (
                f'pulsesrc device="{self.pulse_source}" do-timestamp=true '
                f"! queue max-size-buffers=2 max-size-time=20000000 leaky=downstream "
                f"! audioconvert ! audioresample "
                f"! audio/x-raw,rate=48000,channels=2 "
                f"! opusenc bitrate=96000 frame-size=10 audio-type=restricted-lowdelay "
                f"! rtpopuspay pt=97 "
                f"! queue name=net_audio_queue max-size-buffers=2 max-size-time=20000000 leaky=downstream "
                f"! application/x-rtp,media=audio,encoding-name=OPUS,payload=97 ! wb. "
            )
        else:
            audio_branch = (
                "audiotestsrc wave=silence is-live=true "
                "! audioconvert ! audioresample "
                "! opusenc bitrate=64000 frame-size=20 "
                "! rtpopuspay pt=97 ! wb. "
            )

        return f"webrtcbin name=wb bundle-policy=max-bundle {stun_prop} {turn_prop} {video_branch} {audio_branch}"

    def start(self) -> None:
        with self._lock:
            if self.pipe is not None:
                self._stop_locked()

            desc = self.build_pipeline_description()
            logger.info("Starting GStreamer WebRTC pipeline: %s", desc)
            self.pipe = Gst.parse_launch(desc)
            self.webrtc = self.pipe.get_by_name("wb")
            self.venc = self.pipe.get_by_name("venc")
            self._negotiated = False
            self._remote_desc_set = False
            self._pending_ice = []

            # Lock ICE agent to deterministic port range for router port forwarding (Direct P2P)
            if self.webrtc is not None:
                try:
                    import ctypes
                    gobj = ctypes.CDLL("libgobject-2.0.so.0")
                    gobj.g_object_get.argtypes = [
                        ctypes.c_void_p,
                        ctypes.c_char_p,
                        ctypes.POINTER(ctypes.c_void_p),
                        ctypes.c_void_p,
                    ]
                    gobj.g_object_set.argtypes = [
                        ctypes.c_void_p,
                        ctypes.c_char_p,
                        ctypes.c_uint,
                        ctypes.c_char_p,
                        ctypes.c_uint,
                        ctypes.c_void_p,
                    ]
                    agent_ptr = ctypes.c_void_p()
                    gobj.g_object_get(hash(self.webrtc), b"ice-agent", ctypes.byref(agent_ptr), None)
                    if agent_ptr.value:
                        min_port = int(os.environ.get("RTP_MIN_PORT", "30000"))
                        max_port = int(os.environ.get("RTP_MAX_PORT", "60000"))
                        gobj.g_object_set(agent_ptr, b"min-rtp-port", min_port, b"max-rtp-port", max_port, None)
                        logger.info(
                            "Bound WebRTC ICE RTP port range via ctypes: UDP %d-%d (Direct P2P active)",
                            min_port,
                            max_port,
                        )
                except Exception as exc:
                    logger.debug("Could not configure ICE RTP port range: %s", exc)

            # Register any additional TURN servers (e.g. TCP transport relays)
            if self.turn_servers and self.webrtc is not None:
                for uri in self.turn_servers:
                    try:
                        self.webrtc.emit("add-turn-server", uri)
                    except Exception as exc:
                        logger.warning("add-turn-server failed for %s: %s", uri, exc)

            self.webrtc.connect("on-negotiation-needed", self._on_negotiation_needed)
            self.webrtc.connect("on-ice-candidate", self._on_ice_candidate)
            self.webrtc.connect("on-data-channel", self._on_data_channel)

            bus = self.pipe.get_bus()
            bus.add_signal_watch()
            bus.connect("message::error", self._on_bus_error)
            bus.connect("message::warning", self._on_bus_warning)

            self.pipe.set_state(Gst.State.PLAYING)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self.pipe is not None:
            try:
                self.pipe.set_state(Gst.State.NULL)
            except Exception as exc:
                logger.warning("Error stopping pipeline: %s", exc)
            self.pipe = None
            self.webrtc = None
            self.venc = None
            self.data_channel = None
            self._negotiated = False
            self._remote_desc_set = False
            self._pending_ice = []
            self._last_keyframe_time = 0.0

    def force_keyframe(self) -> bool:
        """
        Request the video encoder to immediately generate an IDR keyframe.
        Used to break client decoder stalls, missing reference frames, and 3-4 FPS packet-loss loops.
        Rate-limited to at most 4 keyframes/sec (250ms interval) to prevent packet bursts.
        """
        now = time.time()
        if now - self._last_keyframe_time < 0.25:
            return False
        self._last_keyframe_time = now

        with self._lock:
            if self.venc is not None:
                try:
                    event = GstVideo.video_event_new_upstream_force_key_unit(
                        Gst.CLOCK_TIME_NONE, True, 0
                    )
                    success = self.venc.send_event(event)
                    logger.info("Sent upstream force-key-unit event to venc (result=%s)", success)
                    return success
                except Exception as exc:
                    logger.warning("Failed to send force-key-unit event: %s", exc)
                    return False
        return False

    def set_quality(self, quality: str) -> Dict[str, object]:
        """Dynamically update NVENC encoder bitrate without restarting the stream."""
        if quality not in QUALITY_PRESETS:
            quality = "high"
        self.quality = quality
        preset = QUALITY_PRESETS[quality]
        with self._lock:
            if self.venc is not None:
                self.venc.set_property("bitrate", preset["bitrate_kbps"])
                logger.info("Updated NVENC bitrate to %d kbps (%s)", preset["bitrate_kbps"], quality)
        return {"quality": quality, **preset}

    def _on_bus_error(self, _bus: Gst.Bus, msg: Gst.Message) -> None:
        err, debug = msg.parse_error()
        logger.error("GStreamer pipeline error: %s (%s)", err, debug)

    def _on_bus_warning(self, _bus: Gst.Bus, msg: Gst.Message) -> None:
        warn, debug = msg.parse_warning()
        logger.warning("GStreamer pipeline warning: %s (%s)", warn, debug)

    def _attach_data_channel_handlers(self, dc: object) -> None:
        self.data_channel = dc
        dc.connect("on-open", self._on_dc_open)
        dc.connect("on-message-string", self._on_dc_message_string)

    def _on_data_channel(self, _webrtc: Gst.Element, dc: object) -> None:
        logger.info("Browser opened RTCDataChannel")
        self._attach_data_channel_handlers(dc)

    def _on_dc_open(self, dc: object) -> None:
        logger.info("RTCDataChannel 'input' is open")
        self.force_keyframe()
        try:
            dc.emit(
                "send-string",
                json.dumps({"type": "hello", "quality": self.quality, "ts": time.time() * 1000.0}),
            )
        except Exception:
            pass

    def _on_dc_message_string(self, dc: object, message: str) -> None:
        try:
            payload = json.loads(message)
        except Exception:
            return

        msg_type = payload.get("type")
        if msg_type == "ping":
            try:
                dc.emit(
                    "send-string",
                    json.dumps(
                        {
                            "type": "pong",
                            "client_ts": payload.get("client_ts"),
                            "server_ts": time.time() * 1000.0,
                        }
                    ),
                )
            except Exception:
                pass
            return

        if msg_type == "quality":
            info = self.set_quality(str(payload.get("quality", "high")))
            try:
                dc.emit("send-string", json.dumps({"type": "quality_ack", **info}))
            except Exception:
                pass
            return

        if msg_type in ("request_keyframe", "keyframe", "pli"):
            forced = self.force_keyframe()
            try:
                dc.emit("send-string", json.dumps({"type": "keyframe_ack", "forced": forced}))
            except Exception:
                pass
            return

        self.on_input_event(payload)

    def _on_negotiation_needed(self, element: Gst.Element) -> None:
        if self._negotiated:
            return
        self._negotiated = True
        try:
            # Low-latency reliable SCTP DataChannel
            dc_opts = Gst.Structure.new_empty("application/data-channel")
            dc_opts.set_value("ordered", True)
            dc = element.emit("create-data-channel", "input", dc_opts)
            if dc is not None:
                self._attach_data_channel_handlers(dc)
        except Exception as exc:
            logger.warning("create-data-channel warning: %s", exc)
            try:
                dc = element.emit("create-data-channel", "input", None)
                if dc is not None:
                    self._attach_data_channel_handlers(dc)
            except Exception:
                pass

        promise = Gst.Promise.new_with_change_func(self._on_offer_created, element, None)
        element.emit("create-offer", None, promise)

    def _on_offer_created(self, promise: Gst.Promise, element: Gst.Element, _user_data: object) -> None:
        reply = promise.get_reply()
        if not reply:
            return
        offer = reply.get_value("offer")
        if not offer:
            return
        element.emit("set-local-description", offer, None)
        sdp_text = offer.sdp.as_text()
        self.on_signaling_message({"type": "offer", "sdp": sdp_text})

    def _on_ice_candidate(self, _element: Gst.Element, mlineindex: int, candidate: str) -> None:
        cand_str = str(candidate)
        ctype = "unknown"
        if " typ " in cand_str:
            ctype = cand_str.split(" typ ")[1].split()[0]
        logger.debug("Emitted local ICE candidate (mline=%d, typ=%s): %s", mlineindex, ctype, cand_str)
        self.on_signaling_message(
            {
                "type": "ice",
                "candidate": candidate,
                "sdpMLineIndex": int(mlineindex),
            }
        )

    def _on_remote_desc_set(self, promise: Gst.Promise, _element: Gst.Element, _user_data: object) -> None:
        with self._lock:
            self._remote_desc_set = True
            logger.info(
                "Remote SDP Answer set on webrtcbin; flushing %d buffered client ICE candidates",
                len(self._pending_ice),
            )
            if self.webrtc is not None:
                for mline, cand in self._pending_ice:
                    try:
                        self.webrtc.emit("add-ice-candidate", int(mline), str(cand))
                    except Exception as exc:
                        logger.warning("Error flushing buffered ICE candidate: %s", exc)
            self._pending_ice = []
            GLib.timeout_add(100, lambda: (self.force_keyframe(), False)[1])

    def handle_sdp_answer(self, sdp_text: str) -> None:
        with self._lock:
            if not self.webrtc:
                return
            res, sdpmsg = GstSdp.SDPMessage.new()
            GstSdp.sdp_message_parse_buffer(bytes(sdp_text.encode("utf-8")), sdpmsg)
            answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg)
            promise = Gst.Promise.new_with_change_func(self._on_remote_desc_set, self.webrtc, None)
            self.webrtc.emit("set-remote-description", answer, promise)

    def handle_ice_candidate(self, mlineindex: int, candidate: str) -> None:
        with self._lock:
            if not self.webrtc or not candidate:
                return
            if not self._remote_desc_set:
                # Buffer until remote description answer promise completes
                self._pending_ice.append((int(mlineindex), str(candidate)))
                return
            self.webrtc.emit("add-ice-candidate", int(mlineindex), candidate)
