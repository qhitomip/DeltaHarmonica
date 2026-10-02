from __future__ import annotations

import threading
import time
import unittest

from PySide6.QtWidgets import QApplication

from delta_harmonica.game_io import GameInput, NOTE_MAP, ToneBand
from delta_harmonica.midi import MidiNote
from delta_harmonica.performer import (
    MidiPerformer, PerformanceState, PerformanceTiming, PlaybackEngine,
    build_performance_schedule, diagnose_schedule,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.stall_at = None
        self.stall_for = 0.0

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.now += seconds
        if self.stall_at is not None and self.now >= self.stall_at:
            self.now += self.stall_for
            self.stall_at = None
        return False


class FakeInput(GameInput):
    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self._active_key = None
        self._active_band = ToneBand.NATURAL
        self.held = set()
        self.events = []
        self.fail_down = False
        self.fail_up = False
        self.before_down = None

    def _send_key(self, key, *, key_up):
        if not key_up and self.before_down:
            self.before_down()
        self.events.append((self.clock(), 'up' if key_up else 'down', key, threading.get_ident()))
        if key_up:
            if self.fail_up:
                raise OSError('fake key-up failure')
            self.held.discard(key)
        else:
            if self.fail_down:
                raise OSError('fake key-down failure')
            if self.held:
                raise AssertionError('two note keys held together')
            self.held.add(key)

    def _send_mouse(self, flags):
        self.events.append((self.clock(), 'mouse', flags, threading.get_ident()))


class EngineTests(unittest.TestCase):
    def run_notes(self, source, speed=100, clock=None):
        clock = clock or FakeClock()
        sender = FakeInput(clock)
        cancel = threading.Event()
        engine = PlaybackEngine(sender, cancel, threading.Lock(), clock=clock, wait=clock.wait)
        timing = PerformanceTiming.for_speed(speed)
        notes = build_performance_schedule(source, timing)
        diagnostics = diagnose_schedule(notes, timing)
        try:
            engine.play(notes, timing, diagnostics, lambda _: None)
        finally:
            sender.release_all()
        return sender, diagnostics, timing

    def test_requested_speeds_preserve_onsets_and_end(self):
        source = [MidiNote(0, .04, 60), MidiNote(.04, .04, 60),
                  MidiNote(.08, .04, 61), MidiNote(.12, .7, 76)]
        for speed in (25, 50, 75, 100, 125, 150):
            with self.subTest(speed=speed):
                timing = PerformanceTiming.for_speed(speed)
                notes = build_performance_schedule(source, timing)
                for original, result in zip(source, notes):
                    self.assertAlmostEqual(original.start * 100 / speed, result.start)
                self.assertAlmostEqual(source[-1].end * 100 / speed, notes[-1].end)
                if speed == 25:
                    self.assertEqual(0, diagnose_schedule(notes, timing).short_notes)
                else:
                    self.assertGreater(diagnose_schedule(notes, timing).short_notes, 0)
                sender, diagnostics, _ = self.run_notes(source, speed)
                self.assertEqual(4, diagnostics.played_notes)
                self.assertEqual(0, diagnostics.skipped_expired_notes)
                downs = [e[0] for e in sender.events if e[1] == 'down']
                for original, actual in zip(source, downs):
                    self.assertAlmostEqual(timing.modifier_lead_seconds + original.start * 100 / speed, actual)
                self.assertFalse(sender.held)

    def test_first_modified_note_gets_full_lead(self):
        sender, _, timing = self.run_notes([MidiNote(0, .2, 48)])
        mouse = next(e[0] for e in sender.events if e[1] == 'mouse')
        down = next(e[0] for e in sender.events if e[1] == 'down')
        self.assertAlmostEqual(timing.modifier_lead_seconds, down - mouse)

    def test_repeated_notes_are_distinct_and_have_release_gaps(self):
        sender, _, _ = self.run_notes([MidiNote(i * .25, .25, 60) for i in range(4)])
        notes = [e for e in sender.events if e[1] in ('up', 'down')]
        self.assertEqual(['down', 'up'] * 4, [e[1] for e in notes])
        for i in (1, 3, 5):
            self.assertAlmostEqual(.025, notes[i + 1][0] - notes[i][0])

    def test_modifier_changes_never_overlap_notes_or_mouse_bands(self):
        source = [MidiNote(i * .2, .2, pitch) for i, pitch in enumerate((48, 61, 76, 60, 50))]
        sender, diagnostics, _ = self.run_notes(source)
        held_note = None
        held_band = None
        downs = {2: 4, 8: 16, 32: 64}
        for _, kind, value, _ in sender.events:
            if kind == 'down':
                self.assertIsNone(held_note)
                held_note = value
            elif kind == 'up':
                held_note = None
            elif value in downs:
                self.assertIsNone(held_note)
                self.assertIsNone(held_band)
                held_band = downs[value]
            else:
                self.assertIsNone(held_note)
                self.assertEqual(held_band, value)
                held_band = None
        self.assertEqual(0, diagnostics.short_modifier_leads)

    def test_late_wakeup_skips_expired_notes_instead_of_burst(self):
        clock = FakeClock()
        clock.stall_at, clock.stall_for = .1, .55
        sender, diagnostics, _ = self.run_notes(
            [MidiNote(i * .15, .1, 60 + i * 2) for i in range(5)], clock=clock)
        self.assertGreaterEqual(diagnostics.skipped_expired_notes, 3)
        downs = [event for event in sender.events if event[1] == 'down']
        self.assertEqual(2, len(downs))
        self.assertGreater(downs[-1][0] - downs[0][0], .5)

    def test_short_last_note_is_not_lengthened(self):
        source = [MidiNote(0, .01, 60)]
        sender, diagnostics, _ = self.run_notes(source)
        down, up = [e for e in sender.events if e[1] in ('up', 'down')]
        self.assertAlmostEqual(.01, up[0] - down[0])
        self.assertEqual(1, diagnostics.short_notes)

    def test_stable_mode_warns_about_dense_notes(self):
        _, diagnostics, _ = self.run_notes([MidiNote(0, .02, 48)])
        self.assertEqual(1, diagnostics.short_notes)
        self.assertEqual(0, diagnostics.short_modifier_leads)  # Stable playback prepares the first modifier.

    def test_cancelled_engine_emits_no_new_down(self):
        clock = FakeClock()
        sender = FakeInput(clock)
        cancel = threading.Event()
        def wait(seconds):
            clock.now += seconds
            if clock.now >= .07:
                cancel.set()
            return cancel.is_set()
        timing = PerformanceTiming.for_speed(100)
        notes = build_performance_schedule([MidiNote(0, 1, 48), MidiNote(1, 1, 61)], timing)
        diagnostics = diagnose_schedule(notes, timing)
        engine = PlaybackEngine(sender, cancel, threading.Lock(), clock=clock, wait=wait)
        engine.play(notes, timing, diagnostics, lambda _: None)
        sender.release_all()
        self.assertEqual(1, diagnostics.played_notes)
        self.assertFalse(sender.held)
        self.assertEqual(ToneBand.NATURAL, sender.active_band)


class PerformerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def pump_until(self, predicate, timeout=2):
        deadline = time.perf_counter() + timeout
        while not predicate() and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(.001)
        self.assertTrue(predicate())

    def test_cancel_countdown_has_no_down_and_can_restart(self):
        sender = FakeInput()
        performer = MidiPerformer(input_factory=lambda: sender)
        source = [MidiNote(0, .02, 48)]
        performer.start(source, 3)
        performer.stop()
        self.pump_until(lambda: not performer.is_running)
        self.assertEqual(PerformanceState.STOPPED, performer.state)
        self.assertFalse(any(e[1] == 'down' for e in sender.events))
        performer.start(source, 0)
        self.pump_until(lambda: not performer.is_running)
        self.assertEqual(PerformanceState.COMPLETED, performer.state)

    def test_rapid_stop_start_waits_for_cleanup_and_starts_from_beginning(self):
        sender = FakeInput()
        performer = MidiPerformer(input_factory=lambda: sender)
        source = [MidiNote(0, 2, 48), MidiNote(2, 1, 61)]
        performer.start(source, 0)
        self.pump_until(lambda: bool(sender.held))
        performer.stop()
        stopped = time.perf_counter()
        performer.start(source, 0)
        self.pump_until(lambda: not performer.is_running)
        self.assertFalse(any(e[1] == 'down' and e[0] > stopped for e in sender.events))
        self.assertFalse(sender.held)
        performer.start(source, 0)
        self.pump_until(lambda: bool(sender.held))
        performer.shutdown()
        self.pump_until(lambda: not performer.is_running)
        downs = [e for e in sender.events if e[1] == 'down']
        self.assertEqual(2, len(downs))
        self.assertEqual(downs[0][2], downs[1][2])
        # GUI thread must never send input, including key-up and mouse cleanup.
        self.assertTrue(all(e[3] != threading.get_ident() for e in sender.events))

    def test_failure_cleans_mouse_band_and_reports_failed(self):
        sender = FakeInput()
        sender.fail_down = True
        performer = MidiPerformer(input_factory=lambda: sender)
        performer.start([MidiNote(0, .2, 48)], 0)
        self.pump_until(lambda: not performer.is_running)
        self.assertEqual(PerformanceState.FAILED, performer.state)
        self.assertEqual(ToneBand.NATURAL, sender.active_band)

    def test_failed_key_release_still_attempts_mouse_release(self):
        sender = FakeInput()
        performer = MidiPerformer(input_factory=lambda: sender)
        performer.start([MidiNote(0, 1, 48)], 0)
        self.pump_until(lambda: bool(sender.held))
        sender.fail_up = True
        performer.shutdown()
        self.pump_until(lambda: not performer.is_running)
        self.assertTrue(performer.diagnostics.cleanup_failed)
        self.assertEqual(PerformanceState.FAILED, performer.state)
        self.assertEqual(ToneBand.NATURAL, sender.active_band)
        sender.fail_up = False
        sender.release_all()

    def test_empty_overlap_and_nonfinite_inputs_rejected(self):
        for notes in ([], [MidiNote(float('nan'), 1, 60)],
                      [MidiNote(0, 1, 60), MidiNote(.5, 1, 62)]):
            performer = MidiPerformer(input_factory=lambda: self.fail('must not create input'))
            performer.start(notes, 0)
            self.assertFalse(performer.is_running)
            self.assertEqual(PerformanceState.FAILED, performer.state)


if __name__ == '__main__':
    unittest.main()
