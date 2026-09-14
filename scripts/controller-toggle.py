#!/usr/bin/env python3
"""Own AntiMicroX, dispatch controller actions, and handle its toggle chord."""
import fcntl
import glob
import json
import os
import select
import signal
import struct
import subprocess
import time

DEVICE_NAME = b"8BitDo Ultimate 2C Wireless Controller"
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
BACK, START = 314, 315  # BTN_SELECT, BTN_START
BUTTON_CONTROLS = {
    304: "a",                 # BTN_SOUTH
    305: "b",                 # BTN_EAST
    307: "x",                 # BTN_NORTH
    308: "y",                 # BTN_WEST
    310: "left_shoulder",     # BTN_TL
    311: "right_shoulder",    # BTN_TR
    316: "guide",             # BTN_MODE
    317: "left_stick",        # BTN_THUMBL
    318: "right_stick",       # BTN_THUMBR
}
DPAD_AXES = {
    16: {-1: "dpad_left", 1: "dpad_right"},
    17: {-1: "dpad_up", 1: "dpad_down"},
}
TRIGGER_AXES = {2: "left_trigger", 5: "right_trigger"}
TRIGGER_THRESHOLD = 128
MODIFIERS = ("ctrl", "shift", "alt", "logo")
PROFILE = os.path.join(CONFIG_HOME, "omarchy", "controller-companion", "omarchy-living-room.amgp")
BACKEND = os.path.join(SCRIPT_DIR, "controller-config.py")
CONFIG = os.path.join(CONFIG_HOME, "omarchy", "controller-companion", "controller-mappings.json")
COMMAND = ["antimicrox", "--hidden", "--no-tray", "--eventgen", "uinput", "--profile", PROFILE]
STATE_DIR = os.path.join(STATE_HOME, "omarchy", "controller-companion")
STATE_FILE = os.path.join(STATE_DIR, "enabled")
PID_FILE = os.path.join(STATE_DIR, "service.pid")

mapper = None
held_modifiers = {}
used_modifiers = set()

def write_file(path, value):
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

def publish_state(enabled):
    write_file(STATE_FILE, "enabled\n" if enabled else "disabled\n")

def mapper_enabled():
    return mapper is not None and mapper.poll() is None

def invoke(control_id, modifiers=()):
    if mapper_enabled():
        subprocess.Popen(
            [BACKEND, "invoke", control_id, *modifiers],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

def mapping_for(control_id):
    try:
        with open(CONFIG, encoding="utf-8") as handle:
            return json.load(handle).get("mappings", {}).get(control_id, {})
    except (OSError, ValueError, TypeError):
        return {}

def active_modifiers():
    active = set(held_modifiers.values())
    return [modifier for modifier in MODIFIERS if modifier in active]

def press_control(control_id):
    if not mapper_enabled():
        return
    mapping = mapping_for(control_id)
    value = mapping.get("value")
    if mapping.get("type") == "key" and value in MODIFIERS:
        held_modifiers[control_id] = value
        used_modifiers.discard(control_id)
        return
    if held_modifiers:
        used_modifiers.update(held_modifiers)
    invoke(control_id, active_modifiers())

def release_control(control_id, suppress_tap=False):
    if control_id not in held_modifiers:
        return
    was_used = control_id in used_modifiers
    held_modifiers.pop(control_id, None)
    used_modifiers.discard(control_id)
    if mapper_enabled() and not suppress_tap and not was_used:
        invoke(control_id)

def clear_held_modifiers():
    held_modifiers.clear()
    used_modifiers.clear()

def find_controller():
    for path in glob.glob("/dev/input/event*"):
        try:
            fd = os.open(path, os.O_RDONLY)
            name = bytearray(256)
            fcntl.ioctl(fd, 0x82004506, name)  # EVIOCGNAME(256)
            if name.split(b"\0", 1)[0] == DEVICE_NAME:
                return fd
            os.close(fd)
        except OSError:
            continue
    return None

def start_mapper():
    global mapper
    if mapper is None or mapper.poll() is not None:
        subprocess.run(
            [BACKEND, "initialize"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.makedirs(STATE_DIR, exist_ok=True)
        log = open(os.path.join(STATE_DIR, "antimicrox.log"), "a", encoding="utf-8")
        mapper = subprocess.Popen(COMMAND, stdout=log, stderr=subprocess.STDOUT)
        publish_state(True)

def stop_mapper(publish=True):
    global mapper
    if mapper is not None and mapper.poll() is None:
        # AntiMicroX 3.6.1 reliably segfaults in its Qt event loop on SIGTERM
        # in hidden/uinput mode. SIGKILL avoids that broken shutdown handler
        # and cannot leave a core dump or a stale virtual input device.
        mapper.kill()
        try:
            mapper.wait(timeout=3)
        except subprocess.TimeoutExpired:
            mapper.kill()
    mapper = None
    clear_held_modifiers()
    if publish:
        publish_state(False)

def toggle_mapper(_signal=None, _frame=None):
    if mapper_enabled():
        stop_mapper()
    else:
        start_mapper()

def restart_mapper(_signal=None, _frame=None):
    was_enabled = mapper_enabled()
    if was_enabled:
        stop_mapper(publish=False)
        start_mapper()

def shutdown(_signal, _frame):
    stop_mapper()
    raise SystemExit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGUSR1, toggle_mapper)
signal.signal(signal.SIGUSR2, restart_mapper)

write_file(PID_FILE, str(os.getpid()) + "\n")
start_mapper()
pressed, latched = set(), False
while True:
    fd = find_controller()
    if fd is None:
        time.sleep(1)
        continue
    axis_values = {}
    try:
        while True:
            readable, _writable, _exceptional = select.select([fd], [], [], 0.5)
            if not readable:
                if mapper is not None and mapper.poll() is not None:
                    mapper = None
                    publish_state(False)
                else:
                    # Keep the shell's displayed state tied to the real process.
                    publish_state(mapper_enabled())
                continue
            data = os.read(fd, 24)
            if len(data) != 24:
                break
            _sec, _usec, event_type, code, value = struct.unpack("llHHi", data)
            if event_type == 1 and code in BUTTON_CONTROLS:
                if value == 1:
                    press_control(BUTTON_CONTROLS[code])
                elif value == 0:
                    release_control(BUTTON_CONTROLS[code])
                continue
            if event_type == 1 and code in (BACK, START):
                if value:
                    pressed.add(code)
                    if mapping_for("back" if code == BACK else "start").get("value") in MODIFIERS:
                        press_control("back" if code == BACK else "start")
                else:
                    pressed.discard(code)
                if pressed == {BACK, START} and not latched:
                    release_control("back", suppress_tap=True)
                    release_control("start", suppress_tap=True)
                    toggle_mapper()
                    latched = True
                elif not value and not latched:
                    # Delay individual Back/Start actions until release so
                    # the toggle chord can suppress both safely.
                    control_id = "back" if code == BACK else "start"
                    if control_id in held_modifiers:
                        release_control(control_id)
                    else:
                        invoke(control_id)
                elif not pressed:
                    latched = False
                continue
            if event_type == 3 and code in DPAD_AXES:
                previous = axis_values.get(code, 0)
                axis_values[code] = value
                if previous in DPAD_AXES[code]:
                    release_control(DPAD_AXES[code][previous])
                if value != previous and value in DPAD_AXES[code]:
                    press_control(DPAD_AXES[code][value])
                continue
            if event_type == 3 and code in TRIGGER_AXES:
                previous = axis_values.get(code, 0)
                axis_values[code] = value
                if previous < TRIGGER_THRESHOLD <= value:
                    press_control(TRIGGER_AXES[code])
                elif previous >= TRIGGER_THRESHOLD > value:
                    release_control(TRIGGER_AXES[code])
    except OSError:
        pass
    finally:
        clear_held_modifiers()
        os.close(fd)
