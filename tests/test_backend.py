import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET


PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "scripts" / "controller-config.py"


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.old_environment = {
            key: os.environ.get(key)
            for key in ("HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME")
        }
        os.environ["HOME"] = str(root / "home")
        os.environ["XDG_CONFIG_HOME"] = str(root / "config")
        os.environ["XDG_STATE_HOME"] = str(root / "state")

        spec = importlib.util.spec_from_file_location("controller_config_test", BACKEND)
        self.backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.backend)

    def tearDown(self):
        for key, value in self.old_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def test_initialize_writes_neutral_defaults(self):
        self.backend.main([str(BACKEND), "initialize"])

        with open(self.backend.CONFIG, encoding="utf-8") as handle:
            config = json.load(handle)

        self.assertEqual(config["mappings"]["a"], {"type": "mouse", "value": "left"})
        self.assertEqual(config["mappings"]["right_shoulder"], {
            "type": "omarchy", "value": "workspace-next"
        })
        self.assertEqual(config["mappings"]["left_trigger"]["type"], "disabled")

    def test_profile_has_no_keyboard_relay_slots(self):
        self.backend.main([str(BACKEND), "initialize"])
        root = ET.parse(self.backend.PROFILE).getroot()
        modes = [node.text for node in root.findall(".//slot/mode")]

        self.assertNotIn("keyboard", modes)
        self.assertIn("mousebutton", modes)
        self.assertIn("mousemovement", modes)

    def test_pointer_and_scroll_scale_one_to_fifty(self):
        data = self.backend.load_config()
        data["mouseSpeed"] = 100
        data["scrollSpeed"] = 100
        self.backend.generate_profile(data)
        root = ET.parse(self.backend.PROFILE).getroot()

        self.assertEqual({node.text for node in root.findall(".//mousespeedx")}, {"50"})
        self.assertEqual({node.text for node in root.findall(".//wheelspeedy")}, {"50"})
        self.assertEqual(self.backend.scaled_speed(1), 1)

    def test_rejects_invalid_mouse_mapping(self):
        with self.assertRaisesRegex(SystemExit, "invalid mouse button"):
            self.backend.main([str(BACKEND), "set", "a", "mouse", "control"])

    def test_held_controller_modifier_wraps_the_next_key(self):
        data = self.backend.load_config()
        data["mappings"]["dpad_left"] = {"type": "key", "value": "Left"}
        self.backend.save_config(data)

        with mock.patch.object(self.backend.subprocess, "Popen") as launch:
            self.backend.main([str(BACKEND), "invoke", "dpad_left", "logo"])

        launch.assert_called_once_with([
            "hyprctl", "eval",
            'hl.dispatch(hl.dsp.focus({ direction = "left" }))'
        ])


if __name__ == "__main__":
    unittest.main()
