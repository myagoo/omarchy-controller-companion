import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


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

        self.assertTrue(config["enabled"])
        self.assertEqual(config["mappings"]["a"], {"type": "mouse", "value": "left"})
        self.assertEqual(
            config["mappings"]["right_shoulder"],
            {"type": "omarchy", "value": "workspace-next"},
        )
        self.assertEqual(config["mappings"]["left_trigger"]["type"], "disabled")

    def test_existing_mappings_survive_initialize(self):
        data = self.backend.load_config()
        data["mouseSpeed"] = 52
        data["mappings"]["right_trigger"] = {"type": "key", "value": "logo"}
        self.backend.save_config(data)

        self.backend.main([str(BACKEND), "initialize"])
        reloaded = self.backend.load_config()

        self.assertEqual(reloaded["mouseSpeed"], 52)
        self.assertEqual(reloaded["mappings"]["right_trigger"]["value"], "logo")

    def test_settings_keep_one_to_one_hundred_panel_range(self):
        with mock.patch.object(self.backend, "signal_service"):
            self.backend.main([str(BACKEND), "settings", "200", "0"])
        data = self.backend.load_config()
        self.assertEqual(data["mouseSpeed"], 100)
        self.assertEqual(data["scrollSpeed"], 1)

    def test_mapping_change_signals_daemon_reload(self):
        with mock.patch.object(self.backend, "signal_service") as notify:
            self.backend.main([str(BACKEND), "set", "a", "key", "Return"])

        self.assertEqual(
            self.backend.load_config()["mappings"]["a"],
            {"type": "key", "value": "Return"},
        )
        notify.assert_called_once_with(self.backend.signal.SIGUSR2)

    def test_rejects_invalid_mouse_mapping(self):
        with self.assertRaisesRegex(SystemExit, "invalid mouse button"):
            self.backend.main([str(BACKEND), "set", "a", "mouse", "control"])


if __name__ == "__main__":
    unittest.main()
