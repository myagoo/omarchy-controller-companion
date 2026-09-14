#!/usr/bin/env python3
"""Configuration and action backend for the Omarchy Controller Companion."""

import json
import os
import configparser
import fcntl
import signal
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
BASE = os.path.join(CONFIG_HOME, "omarchy", "controller-companion")
CONFIG = os.path.join(BASE, "controller-mappings.json")
PROFILE = os.path.join(BASE, "omarchy-living-room.amgp")
STATE_DIR = os.path.join(STATE_HOME, "omarchy", "controller-companion")
PID_FILE = os.path.join(STATE_DIR, "service.pid")

CONTROLS = [
    ("a", "A", "button", 1, 13),
    ("b", "B", "button", 2, 14),
    ("x", "X", "button", 3, 15),
    ("y", "Y", "button", 4, 16),
    ("guide", "Guide", "button", 6, 17),
    ("left_stick", "Left stick click", "button", 8, 18),
    ("right_stick", "Right stick click", "button", 9, 19),
    ("left_shoulder", "Left shoulder", "button", 10, 20),
    ("right_shoulder", "Right shoulder", "button", 11, 21),
    ("dpad_up", "D-pad up", "dpad", 1, 22),
    ("dpad_right", "D-pad right", "dpad", 3, 23),
    ("dpad_down", "D-pad down", "dpad", 5, 24),
    ("dpad_left", "D-pad left", "dpad", 7, 25),
    ("left_trigger", "Left trigger", "trigger", 1, 26),
    ("right_trigger", "Right trigger", "trigger", 2, 27),
]
HELPER_CONTROLS = {"back", "start"}

DEFAULT = {
    "mouseSpeed": 25,
    "scrollSpeed": 10,
    "mappings": {
        "a": {"type": "mouse", "value": "left"},
        "b": {"type": "mouse", "value": "right"},
        "x": {"type": "key", "value": "Tab"},
        "y": {"type": "key", "value": "space"},
        "guide": {"type": "omarchy", "value": "menu"},
        "back": {"type": "disabled", "value": ""},
        "start": {"type": "disabled", "value": ""},
        "left_stick": {"type": "omarchy", "value": "apps"},
        "right_stick": {"type": "omarchy", "value": "keybindings"},
        "left_shoulder": {"type": "omarchy", "value": "workspace-prev"},
        "right_shoulder": {"type": "omarchy", "value": "workspace-next"},
        "dpad_up": {"type": "key", "value": "Up"},
        "dpad_right": {"type": "key", "value": "Right"},
        "dpad_down": {"type": "key", "value": "Down"},
        "dpad_left": {"type": "key", "value": "Left"},
        "left_trigger": {"type": "disabled", "value": ""},
        "right_trigger": {"type": "disabled", "value": ""},
    },
}

OMARCHY_ACTIONS = {
    "menu": ["omarchy-menu", "toggle", "root"],
    "apps": ["omarchy-menu", "toggle", "apps"],
    "keybindings": ["omarchy-menu-keybindings"],
    "system": ["omarchy-menu", "toggle", "system"],
    "workspace-prev": ["hyprctl", "eval", 'hl.dispatch(hl.dsp.focus({ workspace = "e-1" }))'],
    "workspace-next": ["hyprctl", "eval", 'hl.dispatch(hl.dsp.focus({ workspace = "e+1" }))'],
    "close-window": ["hyprctl", "eval", "hl.dispatch(hl.dsp.window.close())"],
    "fullscreen": ["hyprctl", "eval", 'hl.dispatch(hl.dsp.window.fullscreen({ mode = "fullscreen" }))'],
}
MOUSE_CODES = {"left": 1, "middle": 2, "right": 3}
VALID_TYPES = {"key", "omarchy", "app", "mouse", "disabled"}
KEY_MODIFIERS = {"ctrl", "shift", "alt", "logo"}
SINGLE_MODIFIER_KEYS = {
    "ctrl": "Control_L",
    "shift": "Shift_L",
    "alt": "Alt_L",
    "logo": "Super_L",
}
SUPER_ARROW_ACTIONS = {
    "Left": ["hyprctl", "eval", 'hl.dispatch(hl.dsp.focus({ direction = "left" }))'],
    "Right": ["hyprctl", "eval", 'hl.dispatch(hl.dsp.focus({ direction = "right" }))'],
    "Up": ["hyprctl", "eval", 'hl.dispatch(hl.dsp.focus({ direction = "up" }))'],
    "Down": ["hyprctl", "eval", 'hl.dispatch(hl.dsp.focus({ direction = "down" }))'],
}


def load_config():
    data = json.loads(json.dumps(DEFAULT))
    try:
        with open(CONFIG, encoding="utf-8") as handle:
            stored = json.load(handle)
        data.update({k: stored[k] for k in ("mouseSpeed", "scrollSpeed") if k in stored})
        data["mappings"].update(stored.get("mappings", {}))
    except (OSError, ValueError, TypeError):
        pass
    return data


def save_config(data):
    os.makedirs(BASE, exist_ok=True)
    temp = CONFIG + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temp, CONFIG)


def slot(parent, code, mode):
    slots = ET.SubElement(parent, "slots")
    item = ET.SubElement(slots, "slot")
    ET.SubElement(item, "code").text = str(code)
    ET.SubElement(item, "mode").text = mode


def scaled_speed(percent):
    """Map the panel's 1-100% range onto AntiMicroX's useful 1-50 range."""
    percent = max(1, min(100, int(percent)))
    return round(1 + (percent - 1) * 49 / 99)


def action_slot(parent, mapping, f_number):
    if mapping.get("type") == "mouse" and mapping.get("value") in MOUSE_CODES:
        slot(parent, MOUSE_CODES[mapping["value"]], "mousebutton")


def generate_profile(data):
    os.makedirs(BASE, exist_ok=True)
    root = ET.Element("gamecontroller", configversion="19", appversion="3.6.1")
    ET.SubElement(root, "sdlname").text = "8BitDo Ultimate 2C Wireless Controller"
    ET.SubElement(root, "profilename").text = "Omarchy Controller Companion"
    names = ET.SubElement(root, "names")
    ET.SubElement(names, "controlstickname", index="1").text = "Mouse cursor"
    ET.SubElement(names, "controlstickname", index="2").text = "Scroll"
    ET.SubElement(root, "keyPressTime").text = "100"
    sets = ET.SubElement(root, "sets")
    mapping_set = ET.SubElement(sets, "set", index="1")
    ET.SubElement(mapping_set, "name").text = "Living room desktop"

    cursor = ET.SubElement(mapping_set, "stick", index="1")
    ET.SubElement(cursor, "deadZone").text = "8000"
    ET.SubElement(cursor, "maxZone").text = "32000"
    ET.SubElement(cursor, "diagonalRange").text = "65"
    movement_slots = {1: 1, 3: 4, 5: 2, 7: 3}
    cursor_speed = scaled_speed(data["mouseSpeed"])
    for direction in range(1, 9):
        button = ET.SubElement(cursor, "stickbutton", index=str(direction))
        ET.SubElement(button, "mousespeedx").text = str(cursor_speed)
        ET.SubElement(button, "mousespeedy").text = str(cursor_speed)
        ET.SubElement(button, "mousemode").text = "cursor"
        ET.SubElement(button, "mouseacceleration").text = "linear"
        if direction in movement_slots:
            slot(button, movement_slots[direction], "mousemovement")

    scroll = ET.SubElement(mapping_set, "stick", index="2")
    ET.SubElement(scroll, "deadZone").text = "8000"
    ET.SubElement(scroll, "maxZone").text = "32000"
    ET.SubElement(scroll, "mode").text = "four-way"
    for direction, code in ((1, 4), (5, 5)):
        button = ET.SubElement(scroll, "stickbutton", index=str(direction))
        ET.SubElement(button, "wheelspeedy").text = str(scaled_speed(data["scrollSpeed"]))
        slot(button, code, "mousebutton")

    dpad = ET.SubElement(mapping_set, "dpad", index="1")
    for control_id, _label, kind, index, f_number in CONTROLS:
        mapping = data["mappings"].get(control_id, {"type": "disabled", "value": ""})
        if kind == "button":
            node = ET.SubElement(mapping_set, "button", index=str(index))
            ET.SubElement(node, "actionname").text = _label
        elif kind == "dpad":
            node = ET.SubElement(dpad, "dpadbutton", index=str(index))
        else:
            trigger = ET.SubElement(mapping_set, "trigger", index=str(index))
            node = ET.SubElement(trigger, "triggerbutton", index="2")
        action_slot(node, mapping, f_number)

    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    tree.write(PROFILE, encoding="utf-8", xml_declaration=True)


def signal_service(sig):
    try:
        with open(PID_FILE, encoding="utf-8") as handle:
            os.kill(int(handle.read().strip()), sig)
    except (OSError, ValueError):
        return False
    return True


def installed_apps():
    """Return visible desktop applications in the format expected by QML."""
    applications = {}
    roots = ["/usr/share/applications", os.path.expanduser("~/.local/share/applications")]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for directory, _subdirs, filenames in os.walk(root):
            for filename in filenames:
                if not filename.endswith(".desktop"):
                    continue
                path = os.path.join(directory, filename)
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                try:
                    parser.read(path, encoding="utf-8")
                    entry = parser["Desktop Entry"]
                    if entry.get("Type", "Application") != "Application":
                        continue
                    if entry.getboolean("Hidden", fallback=False) or entry.getboolean("NoDisplay", fallback=False):
                        continue
                    name = entry.get("Name", "").strip()
                    if not name or not entry.get("Exec", "").strip():
                        continue
                except (OSError, UnicodeError, configparser.Error, KeyError, ValueError):
                    continue
                relative = os.path.relpath(path, root)
                desktop_id = relative[:-8].replace(os.sep, "-")
                applications[desktop_id] = {"value": desktop_id, "label": name}
    return sorted(applications.values(), key=lambda app: app["label"].casefold())


def type_key(value, extra_modifiers=()):
    if value in SINGLE_MODIFIER_KEYS:
        subprocess.Popen(["wtype", "-k", SINGLE_MODIFIER_KEYS[value]])
        return
    parts = [part for part in value.split("+") if part]
    if not parts:
        return
    key = parts[-1]
    requested_modifiers = set(extra_modifiers) | {
        part for part in parts[:-1] if part in KEY_MODIFIERS
    }
    modifiers = [
        modifier for modifier in ("ctrl", "alt", "shift", "logo")
        if modifier in requested_modifiers
    ]
    if requested_modifiers == {"logo"} and key in SUPER_ARROW_ACTIONS:
        subprocess.Popen(SUPER_ARROW_ACTIONS[key])
        return
    command = ["wtype"]
    for modifier in modifiers:
        command.extend(["-M", modifier])
    command.extend(["-k", key])
    for modifier in reversed(modifiers):
        command.extend(["-m", modifier])
    subprocess.Popen(command)


def mouse_click(value):
    """Emit one Wayland-visible click for helper-owned controller buttons."""
    code = {"left": 272, "right": 273, "middle": 274}.get(value)
    if code is None:
        return
    # Linux uinput ioctls: _IOW('U', n, int) and _IO('U', n).
    ui_set_evbit = 0x40045564
    ui_set_keybit = 0x40045565
    ui_dev_create = 0x5501
    ui_dev_destroy = 0x5502
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, ui_set_evbit, 1)  # EV_KEY
        fcntl.ioctl(fd, ui_set_keybit, code)
        # uinput_user_dev: name, input_id, ff_effects_max, then four ABS arrays.
        header = struct.pack("80sHHHHi", b"Omarchy Controller Companion", 6, 0, 0, 1, 0)
        os.write(fd, header + bytes(64 * 4 * 4))
        fcntl.ioctl(fd, ui_dev_create)
        time.sleep(0.08)
        for event_type, event_code, event_value in (
            (1, code, 1), (0, 0, 0), (1, code, 0), (0, 0, 0)
        ):
            os.write(fd, struct.pack("llHHi", 0, 0, event_type, event_code, event_value))
    finally:
        try:
            fcntl.ioctl(fd, ui_dev_destroy)
        finally:
            os.close(fd)


def invoke(control_id, extra_modifiers=()):
    mapping = load_config()["mappings"].get(control_id, {})
    kind, value = mapping.get("type"), str(mapping.get("value", "")).strip()
    if kind == "key" and value:
        type_key(value, extra_modifiers)
    elif kind == "omarchy" and value in OMARCHY_ACTIONS:
        subprocess.Popen(OMARCHY_ACTIONS[value])
    elif kind == "app" and value:
        subprocess.Popen(["uwsm-app", "--", "gtk-launch", value])
    elif kind == "mouse" and value in MOUSE_CODES and control_id in HELPER_CONTROLS:
        mouse_click(value)


def main(argv):
    command = argv[1] if len(argv) > 1 else "get"
    data = load_config()
    if command == "get":
        print(json.dumps(data))
    elif command == "apps":
        print(json.dumps(installed_apps()))
    elif command == "invoke" and len(argv) >= 3:
        invoke(argv[2], [value for value in argv[3:] if value in KEY_MODIFIERS])
    elif command == "toggle":
        if not signal_service(signal.SIGUSR1):
            raise SystemExit("controller service is not running")
    elif command == "set" and len(argv) >= 5:
        control_id, kind, value = argv[2], argv[3], argv[4]
        if control_id not in ({row[0] for row in CONTROLS} | HELPER_CONTROLS) or kind not in VALID_TYPES:
            raise SystemExit("invalid mapping")
        if kind == "mouse" and value not in MOUSE_CODES:
            raise SystemExit("invalid mouse button")
        if kind == "omarchy" and value not in OMARCHY_ACTIONS:
            raise SystemExit("invalid Omarchy action")
        if kind == "disabled":
            value = ""
        data["mappings"][control_id] = {"type": kind, "value": value}
        save_config(data)
        generate_profile(data)
        signal_service(signal.SIGUSR2)
    elif command == "settings" and len(argv) == 4:
        data["mouseSpeed"] = max(1, min(100, int(argv[2])))
        data["scrollSpeed"] = max(1, min(100, int(argv[3])))
        save_config(data)
        generate_profile(data)
        signal_service(signal.SIGUSR2)
    elif command == "initialize":
        save_config(data)
        generate_profile(data)
    else:
        raise SystemExit("usage: controller-config.py get|apps|toggle|invoke ID|set ID TYPE VALUE|settings MOUSE_PERCENT SCROLL|initialize")


if __name__ == "__main__":
    main(sys.argv)
