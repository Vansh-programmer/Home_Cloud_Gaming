"""
Isolated X11 Kiosk Window Enforcer & Low-Latency Input Injector.

Uses ctypes bindings to libX11.so.6 and libXtst.so.6 to:
1. Enforce fullscreen single-application geometry on the isolated Xwayland display.
2. Inject Keyboard, Mouse (relative Pointer Lock & absolute position), Mouse Wheel,
   Controller (Gamepad API), and Mobile Touch events strictly inside the isolated X server
   so inputs NEVER touch the host desktop.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import threading
import time
from typing import Dict, Optional, Set, Tuple

# X11 Constants
NoSymbol = 0
RevertToPointerRoot = 1
RevertToParent = 2
InputFocus = 1
CurrentTime = 0

# Browser KeyboardEvent.code -> X11 KeySym name mapping
CODE_TO_KEYSYM_NAME: Dict[str, str] = {
    "KeyA": "a", "KeyB": "b", "KeyC": "c", "KeyD": "d", "KeyE": "e",
    "KeyF": "f", "KeyG": "g", "KeyH": "h", "KeyI": "i", "KeyJ": "j",
    "KeyK": "k", "KeyL": "l", "KeyM": "m", "KeyN": "n", "KeyO": "o",
    "KeyP": "p", "KeyQ": "q", "KeyR": "r", "KeyS": "s", "KeyT": "t",
    "KeyU": "u", "KeyV": "v", "KeyW": "w", "KeyX": "x", "KeyY": "y",
    "KeyZ": "z",
    "Digit0": "0", "Digit1": "1", "Digit2": "2", "Digit3": "3", "Digit4": "4",
    "Digit5": "5", "Digit6": "6", "Digit7": "7", "Digit8": "8", "Digit9": "9",
    "Space": "space",
    "Enter": "Return",
    "NumpadEnter": "KP_Enter",
    "Escape": "Escape",
    "Tab": "Tab",
    "Backspace": "BackSpace",
    "Delete": "Delete",
    "Insert": "Insert",
    "Home": "Home",
    "End": "End",
    "PageUp": "Page_Up",
    "PageDown": "Page_Down",
    "ArrowUp": "Up",
    "ArrowDown": "Down",
    "ArrowLeft": "Left",
    "ArrowRight": "Right",
    "ShiftLeft": "Shift_L",
    "ShiftRight": "Shift_R",
    "ControlLeft": "Control_L",
    "ControlRight": "Control_R",
    "AltLeft": "Alt_L",
    "AltRight": "Alt_R",
    "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4",
    "F5": "F5", "F6": "F6", "F7": "F7", "F8": "F8",
    "F9": "F9", "F10": "F10", "F11": "F11", "F12": "F12",
    "Minus": "minus",
    "Equal": "equal",
    "BracketLeft": "bracketleft",
    "BracketRight": "bracketright",
    "Backslash": "backslash",
    "Semicolon": "semicolon",
    "Quote": "apostrophe",
    "Backquote": "grave",
    "Comma": "comma",
    "Period": "period",
    "Slash": "slash",
    "CapsLock": "Caps_Lock",
    "NumLock": "Num_Lock",
    "ScrollLock": "Scroll_Lock",
    "PrintScreen": "Print",
    "Pause": "Pause",
    "ContextMenu": "Menu",
}


class XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("border_width", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p),
        ("root", ctypes.c_ulong),
        ("c_class", ctypes.c_int),
        ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int),
        ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int),
        ("screen", ctypes.c_void_p),
    ]


# Ignore X11 BadWindow errors during asynchronous window enumeration
XErrorHandler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


def _ignore_x_error(display: int, error_event: int) -> int:
    return 0


_c_error_handler = XErrorHandler(_ignore_x_error)


class IsolatedInputManager:
    """Thread-safe XTest input injector and fullscreen window enforcer for an isolated Xwayland display."""

    def __init__(self, display_name: str, width: int = 1920, height: int = 1080) -> None:
        self.display_name = display_name
        self.width = width
        self.height = height
        self._lock = threading.Lock()
        self._dpy: Optional[int] = None
        self._root: int = 0
        self._pressed_keycodes: Set[int] = set()
        self._pressed_buttons: Set[int] = set()
        self._virtual_pad_keys: Set[str] = set()
        self._virtual_touch_keys: Set[str] = set()
        self._ptr_x: int = width // 2
        self._ptr_y: int = height // 2
        self._top_win: int = 0
        self.has_focused_window = False
        self._running = False
        self._wm_thread: Optional[threading.Thread] = None

        self._libX11 = ctypes.cdll.LoadLibrary("libX11.so.6")
        self._libXtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
        self._setup_ctypes()

    def _setup_ctypes(self) -> None:
        self._libX11.XInitThreads()
        self._libX11.XSetErrorHandler.argtypes = [XErrorHandler]
        self._libX11.XSetErrorHandler.restype = ctypes.c_void_p
        self._libX11.XSetErrorHandler(_c_error_handler)

        self._libX11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self._libX11.XOpenDisplay.restype = ctypes.c_void_p

        self._libX11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self._libX11.XCloseDisplay.restype = ctypes.c_int

        self._libX11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self._libX11.XDefaultRootWindow.restype = ctypes.c_ulong

        self._libX11.XFlush.argtypes = [ctypes.c_void_p]
        self._libX11.XFlush.restype = ctypes.c_int

        self._libX11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self._libX11.XStringToKeysym.restype = ctypes.c_ulong

        self._libX11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self._libX11.XKeysymToKeycode.restype = ctypes.c_uint

        self._libX11.XQueryTree.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
            ctypes.POINTER(ctypes.c_uint),
        ]
        self._libX11.XQueryTree.restype = ctypes.c_int

        self._libX11.XFree.argtypes = [ctypes.c_void_p]
        self._libX11.XFree.restype = ctypes.c_int

        self._libX11.XGetWindowAttributes.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(XWindowAttributes),
        ]
        self._libX11.XGetWindowAttributes.restype = ctypes.c_int

        self._libX11.XMoveResizeWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_uint,
        ]
        self._libX11.XMoveResizeWindow.restype = ctypes.c_int

        self._libX11.XSetInputFocus.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self._libX11.XSetInputFocus.restype = ctypes.c_int

        self._libX11.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self._libX11.XRaiseWindow.restype = ctypes.c_int

        self._libXtst.XTestFakeKeyEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self._libXtst.XTestFakeKeyEvent.restype = ctypes.c_int

        self._libXtst.XTestFakeButtonEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self._libXtst.XTestFakeButtonEvent.restype = ctypes.c_int

        self._libXtst.XTestFakeMotionEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self._libXtst.XTestFakeMotionEvent.restype = ctypes.c_int

        self._libXtst.XTestFakeRelativeMotionEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self._libXtst.XTestFakeRelativeMotionEvent.restype = ctypes.c_int

    def connect(self, retries: int = 30, delay: float = 0.1) -> bool:
        """Connect to the isolated Xwayland display and start the kiosk window enforcer."""
        for _ in range(retries):
            with self._lock:
                dpy = self._libX11.XOpenDisplay(self.display_name.encode("utf-8"))
                if dpy:
                    self._dpy = dpy
                    self._root = self._libX11.XDefaultRootWindow(dpy)
                    # Center pointer so PointerRoot focus lands inside fullscreen windows
                    self._libXtst.XTestFakeMotionEvent(
                        dpy, -1, self.width // 2, self.height // 2, CurrentTime
                    )
                    self._libX11.XFlush(dpy)
                    break
            time.sleep(delay)

        if not self._dpy:
            return False

        self._running = True
        self._wm_thread = threading.Thread(target=self._kiosk_window_loop, daemon=True)
        self._wm_thread.start()
        return True

    def close(self) -> None:
        """Release any held keys/buttons and close the X11 connection."""
        self._running = False
        self.release_all_inputs()
        with self._lock:
            if self._dpy:
                self._libX11.XCloseDisplay(self._dpy)
                self._dpy = None

    def _ensure_focus_locked(self) -> None:
        if not self._dpy or not self._root:
            return
        root_ret = ctypes.c_ulong()
        parent_ret = ctypes.c_ulong()
        children_ptr = ctypes.POINTER(ctypes.c_ulong)()
        nchildren = ctypes.c_uint()
        status = self._libX11.XQueryTree(
            self._dpy,
            self._root,
            ctypes.byref(root_ret),
            ctypes.byref(parent_ret),
            ctypes.byref(children_ptr),
            ctypes.byref(nchildren),
        )
        if status and nchildren.value > 0 and bool(children_ptr):
            best_win = 0
            best_area = 0
            best_normal_win = 0
            best_normal_area = 0
            for i in range(nchildren.value):
                win = children_ptr[i]
                attrs = XWindowAttributes()
                if self._libX11.XGetWindowAttributes(self._dpy, win, ctypes.byref(attrs)):
                    # MapState 2 == IsViewable
                    if attrs.map_state == 2 and attrs.width >= 64 and attrs.height >= 64:
                        area = attrs.width * attrs.height
                        if area > best_area:
                            best_area = area
                            best_win = win
                        if not attrs.override_redirect and area > best_normal_area:
                            best_normal_area = area
                            best_normal_win = win

                        # Allow resizing game windows even if Wine/Proton sets override_redirect on borderless windows
                        is_candidate_game_win = (
                            not attrs.override_redirect
                            or (attrs.width >= 320 and attrs.height >= 240)
                        )
                        if is_candidate_game_win and (
                            attrs.x != 0
                            or attrs.y != 0
                            or attrs.width != self.width
                            or attrs.height != self.height
                        ):
                            self._libX11.XMoveResizeWindow(
                                self._dpy, win, 0, 0, self.width, self.height
                            )
            focus_target = best_normal_win or best_win
            if focus_target:
                self._top_win = focus_target
                self._libX11.XRaiseWindow(self._dpy, focus_target)
                if best_normal_win:
                    self._libX11.XSetInputFocus(
                        self._dpy, best_normal_win, RevertToPointerRoot, CurrentTime
                    )
                self._libX11.XFlush(self._dpy)
                self.has_focused_window = True
            self._libX11.XFree(children_ptr)

    def _kiosk_window_loop(self) -> None:
        """
        Single-App Kiosk Window Manager loop:
        Ensures any mapped game window on the isolated X server fills the screen (width x height)
        and holds keyboard input focus.
        """
        while self._running:
            with self._lock:
                self._ensure_focus_locked()
            time.sleep(0.15)

    def _resolve_keycode(self, code: str, key: str = "") -> int:
        if not self._dpy:
            return 0
        keysym_name = CODE_TO_KEYSYM_NAME.get(code)
        if not keysym_name and key:
            if key in CODE_TO_KEYSYM_NAME:
                keysym_name = CODE_TO_KEYSYM_NAME[key]
            elif len(key) == 1:
                keysym_name = key.lower()
            else:
                keysym_name = key
        if not keysym_name:
            return 0
        keysym = self._libX11.XStringToKeysym(keysym_name.encode("utf-8"))
        if keysym == NoSymbol:
            return 0
        return int(self._libX11.XKeysymToKeycode(self._dpy, keysym))

    def send_key(self, code: str, is_pressed: bool, key: str = "") -> None:
        """Inject a key press or release event into the isolated X server."""
        with self._lock:
            if not self._dpy:
                return
            if is_pressed and not self.has_focused_window:
                self._ensure_focus_locked()
            keycode = self._resolve_keycode(code, key)
            if keycode == 0:
                return
            if is_pressed:
                if keycode in self._pressed_keycodes:
                    return
                self._pressed_keycodes.add(keycode)
            else:
                if keycode not in self._pressed_keycodes:
                    return
                self._pressed_keycodes.discard(keycode)
            self._libXtst.XTestFakeKeyEvent(self._dpy, keycode, 1 if is_pressed else 0, CurrentTime)
            self._libX11.XFlush(self._dpy)

    def send_mouse_move(
        self,
        dx: int = 0,
        dy: int = 0,
        abs_x: Optional[float] = None,
        abs_y: Optional[float] = None,
    ) -> None:
        """Inject relative or normalized absolute (0.0..1.0) mouse motion."""
        with self._lock:
            if dx != 0 or dy != 0:
                step_x = max(-100, min(100, int(dx)))
                step_y = max(-100, min(100, int(dy)))
                self._ptr_x = max(0, min(self.width - 1, self._ptr_x + step_x))
                self._ptr_y = max(0, min(self.height - 1, self._ptr_y + step_y))
                if self._dpy:
                    self._libXtst.XTestFakeRelativeMotionEvent(
                        self._dpy, step_x, step_y, CurrentTime
                    )
            elif abs_x is not None and abs_y is not None:
                px = max(0, min(self.width - 1, int(abs_x * self.width)))
                py = max(0, min(self.height - 1, int(abs_y * self.height)))
                self._ptr_x = px
                self._ptr_y = py
                if self._dpy:
                    self._libXtst.XTestFakeMotionEvent(self._dpy, -1, px, py, CurrentTime)
            if self._dpy:
                self._libX11.XFlush(self._dpy)

    def send_mouse_button(self, button: int, is_pressed: bool) -> None:
        """
        Inject mouse button press/release.
        Browser button: 0=Left (X11 1), 1=Middle (X11 2), 2=Right (X11 3).
        """
        x_button_map = {0: 1, 1: 2, 2: 3, 3: 8, 4: 9}
        x_btn = x_button_map.get(button, 1)
        with self._lock:
            if not self._dpy:
                return
            if is_pressed:
                self._pressed_buttons.add(x_btn)
            else:
                self._pressed_buttons.discard(x_btn)
            self._libXtst.XTestFakeButtonEvent(self._dpy, x_btn, 1 if is_pressed else 0, CurrentTime)
            self._libX11.XFlush(self._dpy)

    def send_mouse_wheel(self, delta_x: float, delta_y: float) -> None:
        """Inject vertical (buttons 4/5) or horizontal (buttons 6/7) scroll wheel ticks."""
        with self._lock:
            if not self._dpy:
                return
            if delta_y < 0:
                self._libXtst.XTestFakeButtonEvent(self._dpy, 4, 1, CurrentTime)
                self._libXtst.XTestFakeButtonEvent(self._dpy, 4, 0, CurrentTime)
            elif delta_y > 0:
                self._libXtst.XTestFakeButtonEvent(self._dpy, 5, 1, CurrentTime)
                self._libXtst.XTestFakeButtonEvent(self._dpy, 5, 0, CurrentTime)
            self._libX11.XFlush(self._dpy)

    def handle_gamepad_state(self, axes: list, buttons: list) -> None:
        """
        Translate W3C Gamepad API / Touch Controller state into smooth movement, look,
        and action triggers inside the isolated display.
        Standard W3C layout:
        - axes[0], axes[1]: Left Stick X, Y (Move / Strafe)
        - axes[2], axes[3]: Right Stick X, Y (Camera Look)
        - buttons[0]: A (South -> Space / Jump)
        - buttons[1]: B (East -> Shift / Crouch)
        - buttons[2]: X (West -> Fire / F)
        - buttons[3]: Y (North -> E / Interact)
        - buttons[7]: RT (Right Trigger -> Left Mouse Click / Fire)
        - buttons[12..15]: D-Pad Up, Down, Left, Right
        """
        desired_keys: Set[str] = set()
        lx = float(axes[0]) if len(axes) > 0 else 0.0
        ly = float(axes[1]) if len(axes) > 1 else 0.0
        rx = float(axes[2]) if len(axes) > 2 else 0.0
        ry = float(axes[3]) if len(axes) > 3 else 0.0

        deadzone = 0.18
        mag = (lx * lx + ly * ly) ** 0.5
        if mag > deadzone:
            nx = lx / mag
            ny = ly / mag
            if ny < -0.38:
                desired_keys.add("KeyW")
            elif ny > 0.38:
                desired_keys.add("KeyS")
            if nx < -0.38:
                desired_keys.add("KeyA")
            elif nx > 0.38:
                desired_keys.add("KeyD")
            if mag > 0.85 and ny < -0.38:
                desired_keys.add("ShiftLeft")

        def btn_pressed(idx: int) -> bool:
            if idx >= len(buttons):
                return False
            val = buttons[idx]
            if isinstance(val, dict):
                return bool(val.get("pressed", False))
            return bool(val)

        # D-pad navigation: support both Menu Arrow navigation and WASD movement
        if btn_pressed(12):  # D-pad Up
            desired_keys.add("ArrowUp")
            desired_keys.add("KeyW")
        if btn_pressed(13):  # D-pad Down
            desired_keys.add("ArrowDown")
            desired_keys.add("KeyS")
        if btn_pressed(14):  # D-pad Left
            desired_keys.add("ArrowLeft")
            desired_keys.add("KeyA")
        if btn_pressed(15):  # D-pad Right
            desired_keys.add("ArrowRight")
            desired_keys.add("KeyD")

        # Standard Controller Actions
        if btn_pressed(0):  # A -> Space (Jump) / Enter (Select)
            desired_keys.add("Space")
            desired_keys.add("Enter")
        if btn_pressed(1):  # B -> Shift / Escape (Back)
            desired_keys.add("ShiftLeft")
            desired_keys.add("Escape")
        if btn_pressed(2):  # X -> F / X
            desired_keys.add("KeyF")
            desired_keys.add("KeyX")
        if btn_pressed(3):  # Y -> E / Tab
            desired_keys.add("KeyE")
            desired_keys.add("Tab")
        if btn_pressed(9):  # Start / Menu -> Escape
            desired_keys.add("Escape")
        if btn_pressed(8):  # Back / View / Select -> Tab / Map
            desired_keys.add("Tab")
            desired_keys.add("KeyM")
        if btn_pressed(10):  # L3 -> Sprint
            desired_keys.add("ShiftLeft")
        if btn_pressed(11):  # R3 -> Crouch (C)
            desired_keys.add("KeyC")
        if btn_pressed(5):  # RB -> Fire / F
            desired_keys.add("KeyF")
        if btn_pressed(4):  # LB -> Q
            desired_keys.add("KeyQ")

        # Triggers: RT = Left Click (Fire / Attack / Select), LT = Right Click (Aim / Alt)
        rt_pressed = btn_pressed(7) or (len(buttons) > 7 and float(getattr(buttons[7], "value", buttons[7]) or 0) > 0.4)
        lt_pressed = btn_pressed(6) or (len(buttons) > 6 and float(getattr(buttons[6], "value", buttons[6]) or 0) > 0.4)
        if rt_pressed:
            self.send_mouse_button(0, True)
        elif 1 in self._pressed_buttons:
            self.send_mouse_button(0, False)

        if lt_pressed:
            self.send_mouse_button(2, True)
        elif 3 in self._pressed_buttons:
            self.send_mouse_button(2, False)

        # Diff virtual pad keys against previously active virtual pad keys
        for new_k in desired_keys - self._virtual_pad_keys:
            self.send_key(new_k, True)
        for old_k in self._virtual_pad_keys - desired_keys:
            self.send_key(old_k, False)
        self._virtual_pad_keys = desired_keys

        # Right stick camera look with quadratic precision response curve
        if abs(rx) > deadzone or abs(ry) > deadzone:
            curved_x = rx * (0.45 + 0.55 * abs(rx))
            curved_y = ry * (0.45 + 0.55 * abs(ry))
            look_dx = int(curved_x * 22.0) if abs(rx) > deadzone else 0
            look_dy = int(curved_y * 16.0) if abs(ry) > deadzone else 0
            if look_dx != 0 or look_dy != 0:
                self.send_mouse_move(dx=look_dx, dy=look_dy)

    def handle_touch_move(self, x: float, y: float, sprint: bool = False) -> None:
        """
        Translate virtual analog thumbstick (x, y in -1..1) into 8-way WASD movement
        with circular deadzone and automatic forward sprint at >=78% deflection.
        """
        desired_keys: Set[str] = set()
        mag = (x * x + y * y) ** 0.5
        deadzone = 0.15
        if mag > deadzone:
            nx = x / mag
            ny = y / mag
            # 8-way sector threshold (sin(22.5 deg) ~= 0.382) for natural diagonal movement
            if ny < -0.38:
                desired_keys.add("KeyW")
            elif ny > 0.38:
                desired_keys.add("KeyS")
            if nx < -0.38:
                desired_keys.add("KeyA")
            elif nx > 0.38:
                desired_keys.add("KeyD")
            if sprint or (mag >= 0.78 and ny < -0.30):
                desired_keys.add("ShiftLeft")

        for new_k in desired_keys - self._virtual_touch_keys:
            self.send_key(new_k, True)
        for old_k in self._virtual_touch_keys - desired_keys:
            self.send_key(old_k, False)
        self._virtual_touch_keys = desired_keys

    def release_all_inputs(self) -> None:
        """Safety cleanup: release any held keys or mouse buttons on disconnect."""
        with self._lock:
            self._virtual_pad_keys.clear()
            self._virtual_touch_keys.clear()
            if not self._dpy:
                self._pressed_keycodes.clear()
                self._pressed_buttons.clear()
                return
            for keycode in list(self._pressed_keycodes):
                self._libXtst.XTestFakeKeyEvent(self._dpy, keycode, 0, CurrentTime)
            self._pressed_keycodes.clear()
            for btn in list(self._pressed_buttons):
                self._libXtst.XTestFakeButtonEvent(self._dpy, btn, 0, CurrentTime)
            self._pressed_buttons.clear()
            self._libX11.XFlush(self._dpy)

    def handle_event(self, payload: dict) -> None:
        """Process an incoming JSON input message from the browser DataChannel or WebSocket."""
        ev_type = payload.get("type")
        if ev_type == "keydown":
            self.send_key(str(payload.get("code", "")), True, str(payload.get("key", "")))
        elif ev_type == "keyup":
            self.send_key(str(payload.get("code", "")), False, str(payload.get("key", "")))
        elif ev_type == "mousemove" or ev_type == "touch_look":
            dx = int(payload.get("dx", 0))
            dy = int(payload.get("dy", 0))
            abs_x = payload.get("x")
            abs_y = payload.get("y")
            self.send_mouse_move(
                dx=dx,
                dy=dy,
                abs_x=float(abs_x) if abs_x is not None else None,
                abs_y=float(abs_y) if abs_y is not None else None,
            )
        elif ev_type == "touch_move":
            self.handle_touch_move(
                float(payload.get("x", 0.0)),
                float(payload.get("y", 0.0)),
                bool(payload.get("sprint", False)),
            )
        elif ev_type == "mousedown":
            abs_x = payload.get("x")
            abs_y = payload.get("y")
            if abs_x is not None and abs_y is not None:
                self.send_mouse_move(abs_x=float(abs_x), abs_y=float(abs_y))
            self.send_mouse_button(int(payload.get("button", 0)), True)
        elif ev_type == "mouseup":
            abs_x = payload.get("x")
            abs_y = payload.get("y")
            if abs_x is not None and abs_y is not None:
                self.send_mouse_move(abs_x=float(abs_x), abs_y=float(abs_y))
            self.send_mouse_button(int(payload.get("button", 0)), False)
        elif ev_type == "wheel":
            self.send_mouse_wheel(float(payload.get("dx", 0)), float(payload.get("dy", 0)))
        elif ev_type == "gamepad":
            self.handle_gamepad_state(
                payload.get("axes", []),
                payload.get("buttons", []),
            )
        elif ev_type == "blur" or ev_type == "release_all":
            self.release_all_inputs()
