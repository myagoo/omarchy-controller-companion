#!/usr/bin/env python3
"""Configuration and command backend for Omarchy Controller Companion."""

import configparser
import json
import os
import signal
import subprocess
import sys


CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
BASE = os.path.join(CONFIG_HOME, "omarchy", "controller-companion")
CONFIG = os.path.join(BASE, "controller-mappings.json")
STATE_DIR = os.path.join(STATE_HOME, "omarchy", "controller-companion")
PID_FILE = os.path.join(STATE_DIR, "service.pid")

CONTROLS = [
    "a", "b", "x", "y", "guide", "back", "start",
    "left_stick", "right_stick", "left_shoulder", "right_shoulder",
    "dpad_up", "dpad_right", "dpad_down", "dpad_left",
    "left_trigger", "right_trigger",
]

DEFAULT = {
    "enabled": True,
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
    "workspace-prev": [
        "hyprctl", "eval", 'hl.dispatch(hl.dsp.focus({ workspace = "e-1" }))'
    ],
    "workspace-next": [
        "hyprctl", "eval", 'hl.dispatch(hl.dsp.focus({ workspace = "e+1" }))'
    ],
    "close-window": ["hyprctl", "eval", "hl.dispatch(hl.dsp.window.close())"],
    "fullscreen": [
        "hyprctl", "eval",
        'hl.dispatch(hl.dsp.window.fullscreen({ mode = "fullscreen" }))',
    ],
}

MOUSE_BUTTONS = {"left", "middle", "right"}
VALID_TYPES = {"key", "omarchy", "app", "mouse", "disabled"}


def load_config():
    data = json.loads(json.dumps(DEFAULT))
    try:
        with open(CONFIG, encoding="utf-8") as handle:
            stored = json.load(handle)
        data.update({
            key: stored[key]
            for key in ("enabled", "mouseSpeed", "scrollSpeed")
            if key in stored
        })
        data["mappings"].update(stored.get("mappings", {}))
    except (OSError, ValueError, TypeError):
        pass
    return data


def save_config(data):
    os.makedirs(BASE, exist_ok=True)
    temporary = CONFIG + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, CONFIG)


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
                    if entry.getboolean("Hidden", fallback=False):
                        continue
                    if entry.getboolean("NoDisplay", fallback=False):
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


def invoke(control_id):
    """Run non-input actions; key and mouse events stay in the persistent daemon."""
    mapping = load_config()["mappings"].get(control_id, {})
    kind = mapping.get("type")
    value = str(mapping.get("value", "")).strip()
    command = None
    if kind == "omarchy" and value in OMARCHY_ACTIONS:
        command = OMARCHY_ACTIONS[value]
    elif kind == "app" and value:
        command = ["uwsm-app", "--", "gtk-launch", value]
    if command:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def main(argv):
    command = argv[1] if len(argv) > 1 else "get"
    data = load_config()
    if command == "get":
        print(json.dumps(data))
    elif command == "apps":
        print(json.dumps(installed_apps()))
    elif command == "invoke" and len(argv) == 3:
        invoke(argv[2])
    elif command == "toggle":
        if not signal_service(signal.SIGUSR1):
            raise SystemExit("controller service is not running")
    elif command == "set" and len(argv) >= 5:
        control_id, kind, value = argv[2], argv[3], argv[4]
        if control_id not in CONTROLS or kind not in VALID_TYPES:
            raise SystemExit("invalid mapping")
        if kind == "mouse" and value not in MOUSE_BUTTONS:
            raise SystemExit("invalid mouse button")
        if kind == "omarchy" and value not in OMARCHY_ACTIONS:
            raise SystemExit("invalid Omarchy action")
        if kind == "disabled":
            value = ""
        data["mappings"][control_id] = {"type": kind, "value": value}
        save_config(data)
        signal_service(signal.SIGUSR2)
    elif command == "settings" and len(argv) == 4:
        data["mouseSpeed"] = max(1, min(100, int(argv[2])))
        data["scrollSpeed"] = max(1, min(100, int(argv[3])))
        save_config(data)
        signal_service(signal.SIGUSR2)
    elif command == "initialize":
        save_config(data)
    else:
        raise SystemExit(
            "usage: controller-config.py "
            "get|apps|toggle|invoke ID|set ID TYPE VALUE|"
            "settings MOUSE_PERCENT SCROLL_PERCENT|initialize"
        )


if __name__ == "__main__":
    main(sys.argv)
