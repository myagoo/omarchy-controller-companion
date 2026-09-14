import importlib.util
import math
from pathlib import Path
import unittest
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]
INPUT = PROJECT / "scripts" / "controller_input.py"

spec = importlib.util.spec_from_file_location("controller_input_test", INPUT)
controller_input = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller_input)


class InputTests(unittest.TestCase):
    def test_speed_scale_preserves_one_to_fifty_contract(self):
        self.assertEqual(controller_input.scaled_speed(1), 1)
        self.assertEqual(controller_input.scaled_speed(100), 50)
        self.assertEqual(controller_input.scaled_speed(0), 1)
        self.assertEqual(controller_input.scaled_speed(200), 50)

    def test_stick_dead_zone_and_diagonal_cap(self):
        self.assertEqual(controller_input.normalized_stick(4000, -4000), (0.0, 0.0))
        x, y = controller_input.normalized_stick(32767, 32767)
        self.assertAlmostEqual(math.hypot(x, y), 1.0)
        self.assertAlmostEqual(x, y)

    def test_french_layout_resolves_semantic_a_to_physical_q_position(self):
        resolver = controller_input.KeyResolver(layout="fr", variant="", options="")
        completed = mock.Mock(stdout="KEYCODE  KEY NAME\n24 AD01\n")
        with mock.patch.object(controller_input.subprocess, "run", return_value=completed):
            self.assertEqual(resolver.resolve("a"), 16)

    def test_controller_modifier_is_pressed_with_the_target_key(self):
        resolver = controller_input.KeyResolver(layout="us", variant="", options="")
        with mock.patch.object(resolver, "resolve", return_value=105):
            self.assertEqual(resolver.parse("Left", ["logo"]), [125, 105])

    def test_unknown_key_does_not_emit_an_incomplete_modifier_chord(self):
        resolver = controller_input.KeyResolver(layout="us", variant="", options="")
        completed = mock.Mock(stdout="")
        with mock.patch.object(controller_input.subprocess, "run", return_value=completed):
            self.assertEqual(resolver.parse("Definitely_Not_A_Key", ["logo"]), [])

    def test_keyboard_chord_uses_one_persistent_uinput_device(self):
        resolver = controller_input.KeyResolver(layout="us", variant="", options="")
        keyboard = controller_input.VirtualKeyboard(resolver=resolver, settle=0)
        keyboard.fd = 17
        with mock.patch.object(resolver, "resolve", return_value=105), \
             mock.patch.object(controller_input.os, "write") as write:
            self.assertTrue(keyboard.tap_spec("Left", ["logo"]))

        events = [controller_input.EVENT.unpack(call.args[1])[2:] for call in write.call_args_list]
        self.assertEqual(
            events,
            [
                (controller_input.EV_KEY, 125, 1),
                (controller_input.EV_KEY, 105, 1),
                (controller_input.EV_SYN, 0, 0),
                (controller_input.EV_KEY, 105, 0),
                (controller_input.EV_KEY, 125, 0),
                (controller_input.EV_SYN, 0, 0),
            ],
        )
        self.assertEqual(keyboard.fd, 17)

    def test_pointer_emits_relative_motion_and_scroll(self):
        pointer = controller_input.VirtualPointer(settle=0)
        pointer.fd = 18
        with mock.patch.object(controller_input.os, "write") as write:
            pointer.move(7, -3)
            pointer.scroll(2)

        events = [controller_input.EVENT.unpack(call.args[1])[2:] for call in write.call_args_list]
        self.assertEqual(
            events,
            [
                (controller_input.EV_REL, controller_input.REL_X, 7),
                (controller_input.EV_REL, controller_input.REL_Y, -3),
                (controller_input.EV_SYN, 0, 0),
                (controller_input.EV_REL, controller_input.REL_WHEEL, 2),
                (controller_input.EV_SYN, 0, 0),
            ],
        )


if __name__ == "__main__":
    unittest.main()
