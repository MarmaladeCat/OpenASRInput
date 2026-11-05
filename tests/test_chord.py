import unittest

from openasrinput.domain.chord import ChordGuard, KeyEvent

SHIFT = frozenset({"Shift"})


class ChordTests(unittest.TestCase):
    def test_alt_z_toggles_once_and_consumes_release_after_focus_change(self):
        guard = ChordGuard()
        alt = KeyEvent("Alt_L", True)
        self.assertEqual(guard.handle(alt).forward, ())
        self.assertTrue(guard.handle(KeyEvent("z", True, frozenset({"Alt"}))).toggle)
        guard.reset()
        self.assertEqual(
            guard.handle(KeyEvent("z", True, frozenset({"Alt"}), repeat=True)).forward, ()
        )
        self.assertFalse(guard.handle(KeyEvent("z", True, frozenset({"Alt"}))).toggle)
        self.assertEqual(guard.handle(KeyEvent("z", False)).forward, ())
        self.assertEqual(guard.handle(KeyEvent("Alt_L", False)).forward, ())
        guard.handle(alt)
        self.assertTrue(guard.handle(KeyEvent("z", True, frozenset({"Alt"}))).toggle)

    def test_alt_chord_does_not_leak_alt_tap_into_application_menus(self):
        guard = ChordGuard()
        self.assertFalse(guard.handle(KeyEvent("Alt_L", True)).forward)
        self.assertTrue(guard.handle(KeyEvent("z", True, frozenset({"Alt"}))).toggle)
        self.assertFalse(guard.handle(KeyEvent("z", False)).forward)
        self.assertFalse(guard.handle(KeyEvent("Alt_L", False)).forward)
        down = KeyEvent("Alt_L", True)
        letter = KeyEvent("f", True, frozenset({"Alt"}))
        guard.handle(down)
        self.assertEqual(guard.handle(letter).forward, (down, letter))

    def test_alt_z_rejects_extra_modifiers(self):
        for modifiers in ({"Alt", "Shift"}, {"Alt", "Control"}, set()):
            event = KeyEvent("z", True, frozenset(modifiers))
            decision = ChordGuard().handle(event)
            self.assertFalse(decision.toggle)
            self.assertEqual(decision.forward, (event,))

    def test_voice_chord_consumes_both_halves_and_repeat(self):
        for shift in ("Shift_L", "Shift_R"):
            with self.subTest(shift=shift):
                guard = ChordGuard()
                self.assertEqual(guard.handle(KeyEvent(shift, True)).forward, ())
                self.assertTrue(guard.handle(KeyEvent("Space", True, SHIFT)).toggle)
                for event in (
                    KeyEvent("Space", True, SHIFT, repeat=True),
                    KeyEvent(shift, True, SHIFT, repeat=True),
                    KeyEvent("Space", False, SHIFT),
                    KeyEvent(shift, False),
                ):
                    result = guard.handle(event)
                    self.assertFalse(result.toggle)
                    self.assertEqual(result.forward, ())

    def test_shift_tap_replays_original_down_before_up(self):
        guard = ChordGuard()
        down, up = KeyEvent("Shift_L", True), KeyEvent("Shift_L", False)
        guard.handle(down)
        self.assertEqual(guard.handle(up).forward, (down, up))

    def test_uppercase_replays_shift_before_normal_key(self):
        guard = ChordGuard()
        down, letter = KeyEvent("Shift_R", True), KeyEvent("A", True, SHIFT)
        guard.handle(down)
        self.assertEqual(guard.handle(letter).forward, (down, letter))
        # A Shift already delivered to RIME cannot be retroactively protected.
        self.assertFalse(guard.handle(KeyEvent("Space", True, SHIFT)).toggle)
        self.assertEqual(
            guard.handle(KeyEvent("Shift_R", False)).forward, (KeyEvent("Shift_R", False),)
        )

    def test_extra_modifiers_are_not_voice_shortcuts(self):
        for modifier in ("Control", "Alt", "Super"):
            guard = ChordGuard()
            down = KeyEvent("Shift_L", True)
            space = KeyEvent("Space", True, SHIFT | {modifier})
            guard.handle(down)
            result = guard.handle(space)
            self.assertFalse(result.toggle)
            self.assertEqual(result.forward, (down, space))

    def test_both_shifts_and_reverse_release(self):
        guard = ChordGuard()
        guard.handle(KeyEvent("Shift_L", True))
        guard.handle(KeyEvent("Shift_R", True, SHIFT))
        self.assertTrue(guard.handle(KeyEvent("Space", True, SHIFT)).toggle)
        for event in (
            KeyEvent("Shift_R", False),
            KeyEvent("Shift_L", False),
            KeyEvent("Space", False),
        ):
            self.assertEqual(guard.handle(event).forward, ())

    def test_normal_key_after_chord_restores_still_held_shift(self):
        guard = ChordGuard()
        down = KeyEvent("Shift_L", True)
        guard.handle(down)
        guard.handle(KeyEvent("Space", True, SHIFT))
        guard.handle(KeyEvent("Space", False, SHIFT))
        letter = KeyEvent("A", True, SHIFT)
        self.assertEqual(guard.handle(letter).forward, (down, letter))
        self.assertEqual(
            guard.handle(KeyEvent("Shift_L", False)).forward, (KeyEvent("Shift_L", False),)
        )

    def test_focus_detach_flushes_pending_to_old_context(self):
        guard = ChordGuard()
        down = KeyEvent("Shift_L", True)
        guard.handle(down)
        self.assertEqual(guard.reset().forward, (down,))
        self.assertFalse(guard.handle(KeyEvent("Space", True, SHIFT)).toggle)

    def test_replayed_event_cannot_trigger_recursion(self):
        guard = ChordGuard()
        event = KeyEvent("Shift_L", True, replayed=True)
        self.assertEqual(guard.handle(event).forward, (event,))
        self.assertFalse(guard.handle(KeyEvent("Space", True, SHIFT)).toggle)

    def test_focus_change_mid_chord_requires_fresh_physical_press(self):
        guard = ChordGuard()
        guard.handle(KeyEvent("Shift_L", True))
        guard.handle(KeyEvent("Space", True, SHIFT))
        guard.reset()
        guard.handle(KeyEvent("Space", False, SHIFT))
        self.assertFalse(guard.handle(KeyEvent("Space", True, SHIFT)).toggle)
        guard.handle(KeyEvent("Space", False, SHIFT))
        guard.handle(KeyEvent("Shift_L", False))
        guard.handle(KeyEvent("Shift_L", True))
        self.assertTrue(guard.handle(KeyEvent("Space", True, SHIFT)).toggle)
