#!/usr/bin/env python3
"""Dependency-free controller daemon for Omarchy Controller Companion."""

from __future__ import annotations

import fcntl
import glob
import json
import math
import os
import select
import signal
import struct
import subprocess
import sys
import time

from controller_input import KeyResolver, VirtualKeyboard, VirtualPointer
from controller_input import normalized_stick, scaled_speed


DEVICE_NAME = b"8BitDo Ultimate 2C Wireless Controller"
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
CONFIG = os.path.join(
    CONFIG_HOME, "omarchy", "controller-companion", "controller-mappings.json"
)
BACKEND = os.path.join(SCRIPT_DIR, "controller-config.py")
STATE_DIR = os.path.join(STATE_HOME, "omarchy", "controller-companion")
STATE_FILE = os.path.join(STATE_DIR, "enabled")
PID_FILE = os.path.join(STATE_DIR, "service.pid")

EVENT = struct.Struct("@llHHi")
EV_KEY = 1
EV_ABS = 3
BACK, START = 314, 315
BUTTON_CONTROLS = {
    304: "a",
    305: "b",
    307: "x",
    308: "y",
    310: "left_shoulder",
    311: "right_shoulder",
    316: "guide",
    317: "left_stick",
    318: "right_stick",
}
DPAD_AXES = {
    16: {-1: "dpad_left", 1: "dpad_right"},
    17: {-1: "dpad_up", 1: "dpad_down"},
}
TRIGGER_AXES = {2: "left_trigger", 5: "right_trigger"}
STICK_AXES = {0, 1, 3, 4}
TRIGGER_THRESHOLD = 128
MODIFIERS = ("ctrl", "shift", "alt", "logo")
MOTION_INTERVAL = 0.01


def write_text(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, encoding="utf-8") as handle:
            if handle.read() == value:
                return
    except OSError:
        pass
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(value)
    os.replace(temporary, path)


def read_config() -> dict:
    try:
        with open(CONFIG, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {"enabled": True, "mouseSpeed": 25, "scrollSpeed": 10, "mappings": {}}


def save_config(data: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    temporary = CONFIG + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, CONFIG)


def find_controller() -> int | None:
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            name = bytearray(256)
            fcntl.ioctl(fd, 0x82004506, name)  # EVIOCGNAME(256)
            if name.split(b"\0", 1)[0] == DEVICE_NAME:
                return fd
            os.close(fd)
        except OSError:
            continue
    return None


class ControllerDaemon:
    def __init__(self, keyboard=None, pointer=None):
        self.keyboard = keyboard or VirtualKeyboard()
        self.pointer = pointer or VirtualPointer()
        self.config = read_config()
        self.enabled = bool(self.config.get("enabled", True))
        self.running = True
        self.toggle_requested = False
        self.reload_requested = False
        self.controller_fd: int | None = None
        self.held_modifiers: dict[str, str] = {}
        self.used_modifiers: set[str] = set()
        self.pressed: set[int] = set()
        self.toggle_latched = False
        self.axes = {code: 0 for code in (*STICK_AXES, *TRIGGER_AXES, *DPAD_AXES)}
        self.mouse_remainder = [0.0, 0.0]
        self.scroll_remainder = 0.0
        self.last_motion = time.monotonic()

    def publish_state(self) -> None:
        write_text(STATE_FILE, "enabled\n" if self.enabled else "disabled\n")

    def mapping_for(self, control_id: str) -> dict:
        mappings = self.config.get("mappings", {})
        mapping = mappings.get(control_id, {}) if isinstance(mappings, dict) else {}
        return mapping if isinstance(mapping, dict) else {}

    def active_modifiers(self) -> list[str]:
        active = set(self.held_modifiers.values())
        return [name for name in MODIFIERS if name in active]

    def invoke(self, control_id: str, modifiers=()) -> None:
        if not self.enabled:
            return
        mapping = self.mapping_for(control_id)
        kind = mapping.get("type")
        value = str(mapping.get("value", "")).strip()
        if kind == "key" and value:
            if not self.keyboard.tap_spec(value, modifiers):
                print(f"Controller Companion: unsupported key mapping {value!r}", file=sys.stderr)
        elif kind == "mouse":
            self.pointer.click(value)
        elif kind in {"omarchy", "app"} and value:
            subprocess.Popen(
                [BACKEND, "invoke", control_id],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    def press_control(self, control_id: str) -> None:
        if not self.enabled:
            return
        mapping = self.mapping_for(control_id)
        value = str(mapping.get("value", "")).strip().lower()
        if mapping.get("type") == "key" and value in MODIFIERS:
            self.held_modifiers[control_id] = value
            self.used_modifiers.discard(control_id)
            return
        if self.held_modifiers:
            self.used_modifiers.update(self.held_modifiers)
        self.invoke(control_id, self.active_modifiers())

    def release_control(self, control_id: str, suppress_tap: bool = False) -> None:
        if control_id not in self.held_modifiers:
            return
        was_used = control_id in self.used_modifiers
        self.held_modifiers.pop(control_id, None)
        self.used_modifiers.discard(control_id)
        if self.enabled and not suppress_tap and not was_used:
            self.invoke(control_id)

    def clear_held(self) -> None:
        self.held_modifiers.clear()
        self.used_modifiers.clear()

    def reload(self) -> None:
        self.config = read_config()
        self.enabled = bool(self.config.get("enabled", True))
        if hasattr(self.keyboard, "resolver"):
            self.keyboard.resolver = KeyResolver()
        self.publish_state()

    def toggle(self) -> None:
        data = read_config()
        self.enabled = not bool(data.get("enabled", True))
        data["enabled"] = self.enabled
        save_config(data)
        self.config = data
        self.clear_held()
        self.publish_state()

    def request_toggle(self, _signal=None, _frame=None) -> None:
        self.toggle_requested = True

    def request_reload(self, _signal=None, _frame=None) -> None:
        self.reload_requested = True

    def request_stop(self, _signal=None, _frame=None) -> None:
        self.running = False

    def _handle_back_start(self, code: int, value: int) -> None:
        control_id = "back" if code == BACK else "start"
        if value:
            self.pressed.add(code)
            mapping = self.mapping_for(control_id)
            if str(mapping.get("value", "")).lower() in MODIFIERS:
                self.press_control(control_id)
        else:
            self.pressed.discard(code)

        if self.pressed == {BACK, START} and not self.toggle_latched:
            self.release_control("back", suppress_tap=True)
            self.release_control("start", suppress_tap=True)
            self.toggle()
            self.toggle_latched = True
        elif not value and not self.toggle_latched:
            if control_id in self.held_modifiers:
                self.release_control(control_id)
            else:
                self.invoke(control_id)
        elif not self.pressed:
            self.toggle_latched = False

    def handle_event(self, event_type: int, code: int, value: int) -> None:
        if event_type == EV_KEY and code in BUTTON_CONTROLS:
            if value == 1:
                self.press_control(BUTTON_CONTROLS[code])
            elif value == 0:
                self.release_control(BUTTON_CONTROLS[code])
            return
        if event_type == EV_KEY and code in (BACK, START):
            self._handle_back_start(code, value)
            return
        if event_type != EV_ABS:
            return

        previous = self.axes.get(code, 0)
        self.axes[code] = value
        if code in DPAD_AXES:
            if previous in DPAD_AXES[code]:
                self.release_control(DPAD_AXES[code][previous])
            if value != previous and value in DPAD_AXES[code]:
                self.press_control(DPAD_AXES[code][value])
        elif code in TRIGGER_AXES:
            if previous < TRIGGER_THRESHOLD <= value:
                self.press_control(TRIGGER_AXES[code])
            elif previous >= TRIGGER_THRESHOLD > value:
                self.release_control(TRIGGER_AXES[code])

    def motion_active(self) -> bool:
        pointer_x, pointer_y = normalized_stick(self.axes[0], self.axes[1])
        _scroll_x, scroll_y = normalized_stick(self.axes[3], self.axes[4])
        return bool(pointer_x or pointer_y or scroll_y)

    def motion_tick(self, now: float) -> None:
        elapsed = max(0.0, min(0.05, now - self.last_motion))
        self.last_motion = now
        if not self.enabled or self.controller_fd is None:
            self.mouse_remainder[:] = [0.0, 0.0]
            self.scroll_remainder = 0.0
            return

        pointer_x, pointer_y = normalized_stick(self.axes[0], self.axes[1])
        if pointer_x or pointer_y:
            pixels_per_second = scaled_speed(self.config.get("mouseSpeed", 25)) * 100
            self.mouse_remainder[0] += pointer_x * pixels_per_second * elapsed
            self.mouse_remainder[1] += pointer_y * pixels_per_second * elapsed
            move_x = math.trunc(self.mouse_remainder[0])
            move_y = math.trunc(self.mouse_remainder[1])
            self.mouse_remainder[0] -= move_x
            self.mouse_remainder[1] -= move_y
            self.pointer.move(move_x, move_y)
        else:
            self.mouse_remainder[:] = [0.0, 0.0]

        _scroll_x, scroll_y = normalized_stick(self.axes[3], self.axes[4])
        if scroll_y:
            wheels_per_second = scaled_speed(self.config.get("scrollSpeed", 10))
            self.scroll_remainder += -scroll_y * wheels_per_second * elapsed
            steps = math.trunc(self.scroll_remainder)
            self.scroll_remainder -= steps
            self.pointer.scroll(steps)
        else:
            self.scroll_remainder = 0.0

    def _read_controller(self) -> bool:
        assert self.controller_fd is not None
        try:
            data = os.read(self.controller_fd, EVENT.size * 64)
        except BlockingIOError:
            return True
        except OSError:
            return False
        if not data:
            return False
        for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
            _sec, _usec, event_type, code, value = EVENT.unpack_from(data, offset)
            self.handle_event(event_type, code, value)
        return True

    def _disconnect(self) -> None:
        if self.controller_fd is not None:
            os.close(self.controller_fd)
            self.controller_fd = None
        self.axes = {code: 0 for code in (*STICK_AXES, *TRIGGER_AXES, *DPAD_AXES)}
        self.pressed.clear()
        self.toggle_latched = False
        self.clear_held()

    def run(self) -> None:
        os.makedirs(STATE_DIR, exist_ok=True)
        write_text(PID_FILE, f"{os.getpid()}\n")
        self.keyboard.open()
        self.pointer.open()
        self.publish_state()
        signal.signal(signal.SIGUSR1, self.request_toggle)
        signal.signal(signal.SIGUSR2, self.request_reload)
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        next_scan = 0.0
        self.last_motion = time.monotonic()

        try:
            while self.running:
                if self.toggle_requested:
                    self.toggle_requested = False
                    self.toggle()
                if self.reload_requested:
                    self.reload_requested = False
                    self.reload()

                now = time.monotonic()
                if self.controller_fd is None and now >= next_scan:
                    self.controller_fd = find_controller()
                    next_scan = now + 1.0

                timeout = MOTION_INTERVAL if self.motion_active() else 0.25
                readers = [self.controller_fd] if self.controller_fd is not None else []
                try:
                    ready, _writable, _exceptional = select.select(readers, [], [], timeout)
                except (InterruptedError, OSError):
                    ready = []
                if ready and not self._read_controller():
                    self._disconnect()
                    next_scan = time.monotonic() + 1.0
                self.motion_tick(time.monotonic())
        finally:
            self._disconnect()
            self.pointer.close()
            self.keyboard.close()
            write_text(STATE_FILE, "disabled\n")
            try:
                with open(PID_FILE, encoding="utf-8") as handle:
                    owned = handle.read().strip() == str(os.getpid())
                if owned:
                    os.unlink(PID_FILE)
            except OSError:
                pass


def main() -> int:
    try:
        subprocess.run(
            [BACKEND, "initialize"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ControllerDaemon().run()
        return 0
    except OSError as error:
        write_text(STATE_FILE, "disabled\n")
        print(f"Controller Companion: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
