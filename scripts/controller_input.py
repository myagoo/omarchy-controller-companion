#!/usr/bin/env python3
"""Pure-stdlib evdev/uinput support for Controller Companion."""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import struct
import subprocess
import time


EV_SYN = 0
EV_KEY = 1
EV_REL = 2
SYN_REPORT = 0
REL_X = 0
REL_Y = 1
REL_HWHEEL = 6
REL_WHEEL = 8

def _ioc(direction: int, letter: str, number: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(letter) << 8) | number


UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_DEV_SETUP = _ioc(1, "U", 3, struct.calcsize("HHHH80sI"))
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566

EVENT = struct.Struct("@llHHi")

MOUSE_BUTTONS = {"left": 272, "right": 273, "middle": 274}
MODIFIER_CODES = {"ctrl": 29, "shift": 42, "alt": 56, "logo": 125}
MODIFIER_ALIASES = {
    "control": "ctrl",
    "meta": "logo",
    "super": "logo",
    "win": "logo",
}

# Used only when xkbcli is unavailable. The normal path resolves keysyms using
# Hyprland's active layout, which keeps semantic mappings correct on AZERTY.
FALLBACK_KEY_CODES = {
    "Escape": 1,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6,
    "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "minus": 12, "equal": 13, "BackSpace": 14, "Tab": 15,
    "q": 16, "w": 17, "e": 18, "r": 19, "t": 20,
    "y": 21, "u": 22, "i": 23, "o": 24, "p": 25,
    "bracketleft": 26, "bracketright": 27, "Return": 28,
    "a": 30, "s": 31, "d": 32, "f": 33, "g": 34,
    "h": 35, "j": 36, "k": 37, "l": 38,
    "semicolon": 39, "apostrophe": 40, "grave": 41,
    "backslash": 43, "z": 44, "x": 45, "c": 46,
    "v": 47, "b": 48, "n": 49, "m": 50,
    "comma": 51, "period": 52, "slash": 53, "space": 57,
    "F1": 59, "F2": 60, "F3": 61, "F4": 62, "F5": 63,
    "F6": 64, "F7": 65, "F8": 66, "F9": 67, "F10": 68,
    "F11": 87, "F12": 88, "KP_Enter": 96,
    "Home": 102, "Up": 103, "Page_Up": 104, "Left": 105,
    "Right": 106, "End": 107, "Down": 108, "Page_Down": 109,
    "Insert": 110, "Delete": 111,
}
FALLBACK_KEY_CODES.update({f"F{number}": 170 + number for number in range(13, 25)})


def pack_event(event_type: int, code: int, value: int) -> bytes:
    return EVENT.pack(0, 0, event_type, code, value)


def scaled_speed(percent: int) -> int:
    """Map the panel's 1-100 range linearly onto the established 1-50 range."""
    percent = max(1, min(100, int(percent)))
    return round(1 + (percent - 1) * 49 / 99)


def normalized_stick(x: int, y: int, dead_zone: float = 8000 / 32768) -> tuple[float, float]:
    """Return a radial-deadzoned, linear stick vector with magnitude at most one."""
    nx = max(-1.0, min(1.0, x / 32767 if x >= 0 else x / 32768))
    ny = max(-1.0, min(1.0, y / 32767 if y >= 0 else y / 32768))
    magnitude = math.hypot(nx, ny)
    if magnitude <= dead_zone:
        return 0.0, 0.0
    direction_x, direction_y = nx / magnitude, ny / magnitude
    output = min(1.0, (magnitude - dead_zone) / (1.0 - dead_zone))
    return direction_x * output, direction_y * output


def _hypr_option(name: str) -> str:
    try:
        result = subprocess.run(
            ["hyprctl", "-j", "getoption", name],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        return str(json.loads(result.stdout).get("str", "")).strip()
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return ""


class KeyResolver:
    """Translate captured XKB keysyms into physical evdev codes."""

    def __init__(self, layout: str | None = None, variant: str | None = None,
                 options: str | None = None):
        self.layout = (layout if layout is not None else _hypr_option("input:kb_layout"))
        self.variant = (variant if variant is not None else _hypr_option("input:kb_variant"))
        self.options = (options if options is not None else _hypr_option("input:kb_options"))
        self.layout = self.layout.split(",", 1)[0] or "us"
        self.variant = self.variant.split(",", 1)[0]
        self._cache: dict[str, int | None] = {}

    @staticmethod
    def modifier_name(value: str) -> str:
        value = value.strip().lower()
        return MODIFIER_ALIASES.get(value, value) if value else ""

    def resolve(self, key: str) -> int | None:
        modifier = self.modifier_name(key)
        if modifier in MODIFIER_CODES:
            return MODIFIER_CODES[modifier]
        if key in self._cache:
            return self._cache[key]

        command = ["xkbcli", "how-to-type", "--layout", self.layout]
        if self.variant:
            command.extend(["--variant", self.variant])
        if self.options:
            command.extend(["--options", self.options])
        command.extend(["--keysym", key])
        code = None
        try:
            result = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            )
            for line in result.stdout.splitlines():
                match = re.match(r"\s*(\d+)\s+\S+", line)
                if match and int(match.group(1)) >= 8:
                    code = int(match.group(1)) - 8
                    break
        except (OSError, subprocess.TimeoutExpired):
            pass
        if code is None:
            code = FALLBACK_KEY_CODES.get(key)
        self._cache[key] = code
        return code

    def parse(self, spec: str, extra_modifiers=()) -> list[int]:
        parts = [part.strip() for part in str(spec).split("+") if part.strip()]
        if not parts:
            return []
        if len(parts) == 1 and self.modifier_name(parts[0]) in MODIFIER_CODES:
            return [MODIFIER_CODES[self.modifier_name(parts[0])]]

        requested = {
            self.modifier_name(value)
            for value in [*extra_modifiers, *parts[:-1]]
            if self.modifier_name(value) in MODIFIER_CODES
        }
        codes = [
            MODIFIER_CODES[name]
            for name in ("ctrl", "alt", "shift", "logo")
            if name in requested
        ]
        key_code = self.resolve(parts[-1])
        if key_code is None:
            return []
        if key_code not in codes:
            codes.append(key_code)
        return codes


class UInputDevice:
    """Small persistent uinput device using only the Linux kernel ABI."""

    def __init__(self, name: str, *, key_codes=(), relative_codes=(), settle=0.0):
        self.name = name
        self.key_codes = tuple(sorted(set(key_codes)))
        self.relative_codes = tuple(sorted(set(relative_codes)))
        self.settle = settle
        self.fd: int | None = None

    def open(self) -> None:
        if self.fd is not None:
            return
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
            if self.key_codes:
                fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
                for code in self.key_codes:
                    fcntl.ioctl(fd, UI_SET_KEYBIT, code)
            if self.relative_codes:
                fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
                for code in self.relative_codes:
                    fcntl.ioctl(fd, UI_SET_RELBIT, code)
            setup = struct.pack(
                "HHHH80sI", 3, 0x1D6B, 0xCC02, 1, self.name.encode()[:79], 0
            )
            fcntl.ioctl(fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(fd, UI_DEV_CREATE)
        except OSError:
            os.close(fd)
            raise
        self.fd = fd
        if self.settle:
            time.sleep(self.settle)

    def close(self) -> None:
        if self.fd is None:
            return
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(self.fd)
        finally:
            self.fd = None

    def emit(self, event_type: int, code: int, value: int) -> None:
        self.open()
        assert self.fd is not None
        os.write(self.fd, pack_event(event_type, code, value))

    def sync(self) -> None:
        self.emit(EV_SYN, SYN_REPORT, 0)


class VirtualKeyboard(UInputDevice):
    def __init__(self, resolver: KeyResolver | None = None, settle: float = 0.4):
        all_codes = set(FALLBACK_KEY_CODES.values()) | set(MODIFIER_CODES.values())
        super().__init__(
            "Omarchy Controller Companion Keyboard",
            key_codes=all_codes,
            settle=settle,
        )
        self.resolver = resolver or KeyResolver()

    def tap(self, codes: list[int], gap: float = 0.012) -> bool:
        if not codes:
            return False
        for code in codes:
            self.emit(EV_KEY, code, 1)
        self.sync()
        if gap:
            time.sleep(gap)
        for code in reversed(codes):
            self.emit(EV_KEY, code, 0)
        self.sync()
        return True

    def tap_spec(self, spec: str, extra_modifiers=()) -> bool:
        return self.tap(self.resolver.parse(spec, extra_modifiers))


class VirtualPointer(UInputDevice):
    HYPRLAND_NAME = "omarchy-controller-companion-pointer"

    def __init__(self, settle: float = 0.15):
        super().__init__(
            "Omarchy Controller Companion Pointer",
            key_codes=MOUSE_BUTTONS.values(),
            relative_codes=(REL_X, REL_Y, REL_HWHEEL, REL_WHEEL),
            settle=settle,
        )

    def open(self) -> None:
        already_open = self.fd is not None
        super().open()
        if already_open:
            return
        # Apply only to our virtual pointer and only at runtime. The plugin does
        # not edit the user's Hyprland configuration.
        try:
            subprocess.run(
                [
                    "hyprctl",
                    "eval",
                    "hl.device({ "
                    f'name = "{self.HYPRLAND_NAME}", '
                    'accel_profile = "flat", sensitivity = 0 })',
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def move(self, x: int, y: int) -> None:
        if x:
            self.emit(EV_REL, REL_X, x)
        if y:
            self.emit(EV_REL, REL_Y, y)
        if x or y:
            self.sync()

    def scroll(self, vertical: int, horizontal: int = 0) -> None:
        if vertical:
            self.emit(EV_REL, REL_WHEEL, vertical)
        if horizontal:
            self.emit(EV_REL, REL_HWHEEL, horizontal)
        if vertical or horizontal:
            self.sync()

    def click(self, button: str, gap: float = 0.012) -> bool:
        code = MOUSE_BUTTONS.get(button)
        if code is None:
            return False
        self.emit(EV_KEY, code, 1)
        self.sync()
        if gap:
            time.sleep(gap)
        self.emit(EV_KEY, code, 0)
        self.sync()
        return True
