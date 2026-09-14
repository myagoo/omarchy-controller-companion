import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT / "scripts"
sys.path.insert(0, str(SCRIPTS))
DAEMON = SCRIPTS / "controller-toggle.py"
spec = importlib.util.spec_from_file_location("controller_toggle_test", DAEMON)
controller_toggle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller_toggle)


class FakeKeyboard:
    def __init__(self):
        self.calls = []

    def tap_spec(self, value, modifiers=()):
        self.calls.append((value, list(modifiers)))
        return True

    def open(self):
        pass

    def close(self):
        pass


class FakePointer:
    def __init__(self):
        self.moves = []
        self.scrolls = []
        self.clicks = []

    def move(self, x, y):
        if x or y:
            self.moves.append((x, y))

    def scroll(self, vertical, horizontal=0):
        if vertical or horizontal:
            self.scrolls.append((vertical, horizontal))

    def click(self, button):
        self.clicks.append(button)
        return True

    def open(self):
        pass

    def close(self):
        pass


class DaemonTests(unittest.TestCase):
    def daemon(self, mappings=None, mouse_speed=25, scroll_speed=10):
        config = {
            "enabled": True,
            "mouseSpeed": mouse_speed,
            "scrollSpeed": scroll_speed,
            "mappings": mappings or {},
        }
        keyboard, pointer = FakeKeyboard(), FakePointer()
        with mock.patch.object(controller_toggle, "read_config", return_value=config):
            daemon = controller_toggle.ControllerDaemon(keyboard, pointer)
        return daemon, keyboard, pointer

    def test_held_super_wraps_the_next_controller_key(self):
        daemon, keyboard, _pointer = self.daemon({
            "right_trigger": {"type": "key", "value": "logo"},
            "dpad_left": {"type": "key", "value": "Left"},
        })

        daemon.press_control("right_trigger")
        daemon.press_control("dpad_left")
        daemon.release_control("right_trigger")

        self.assertEqual(keyboard.calls, [("Left", ["logo"])])

    def test_mouse_mapping_uses_persistent_pointer(self):
        daemon, _keyboard, pointer = self.daemon({
            "a": {"type": "mouse", "value": "left"},
        })

        daemon.press_control("a")

        self.assertEqual(pointer.clicks, ["left"])

    def test_full_stick_uses_fifty_units_at_one_hundred_percent(self):
        daemon, _keyboard, pointer = self.daemon(mouse_speed=100, scroll_speed=100)
        daemon.controller_fd = 99
        daemon.axes[0] = 32767
        daemon.last_motion = 1.0

        daemon.motion_tick(1.01)

        self.assertEqual(pointer.moves, [(50, 0)])

    def test_full_scroll_stick_accumulates_fifty_steps_per_second(self):
        daemon, _keyboard, pointer = self.daemon(mouse_speed=100, scroll_speed=100)
        daemon.controller_fd = 99
        daemon.axes[4] = -32768
        daemon.last_motion = 1.0

        daemon.motion_tick(1.01)
        daemon.motion_tick(1.02)

        self.assertEqual(pointer.scrolls, [(1, 0)])


if __name__ == "__main__":
    unittest.main()
