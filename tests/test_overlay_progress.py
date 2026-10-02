import os
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from delta_harmonica.overlay import PlaybackOverlay
from delta_harmonica.midi import MidiNote
from delta_harmonica.performer import PlaybackEngine, PerformanceTiming, build_performance_schedule, diagnose_schedule
from delta_harmonica.ui import MainWindow
from test_playback import FakeClock, FakeInput


class OverlayProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.clock = FakeClock()
        self.overlay = PlaybackOverlay(clock=self.clock)
        self.overlay.set_enabled(False)

    def tearDown(self):
        self.overlay.close()

    def test_countdown_excludes_time_and_delayed_delivery_uses_engine_epoch(self):
        o = self.overlay
        o.begin('song', 100, 'F6', 100)
        o.set_state('3 秒后开始')
        self.clock.now = 20
        o._update_progress()
        self.assertEqual(0, o.elapsed)
        self.assertEqual('-01:40', o.remaining_label.text())
        self.assertFalse(o.progress_timer.isActive())
        o.start_timeline(10, 100)
        self.assertEqual(10, o.elapsed)
        self.assertEqual(100, o.progress.value())
        self.clock.now = 40.2
        o._update_progress()
        self.assertEqual('00:30', o.elapsed_label.text())
        self.assertEqual('-01:10', o.remaining_label.text())

    def test_stop_failure_completion_restart_and_timer_cleanup(self):
        o = self.overlay
        for terminal in ('正在停止并释放按键', '已停止', '演奏失败'):
            self.clock.now = 0
            o.begin('song', 100, 'F6', 120)
            o.start_timeline(0, 120)
            self.clock.now = 25
            o.set_state(terminal)
            self.clock.now = 50
            o._update_progress()
            self.assertEqual(25, o.elapsed)
            self.assertFalse(o.progress_timer.isActive())
            o.start_timeline(0, 120)
            self.assertFalse(o.progress_timer.isActive())
        o.begin('new', 150, 'F7', 40)
        self.assertEqual('00:00', o.elapsed_label.text())
        self.assertEqual('-00:40', o.remaining_label.text())
        self.assertEqual(0, o.progress.value())
        o.start_timeline(50, 40)
        o.set_state('演奏完成')
        self.assertEqual(1000, o.progress.value())
        self.assertEqual('-00:00', o.remaining_label.text())
        self.assertFalse(o.progress_timer.isActive())
        o.begin('closing', 100, 'F6', 10)
        o.start_timeline(50, 10)
        o.close()
        self.assertFalse(o.progress_timer.isActive())

    def test_zero_duration_and_bounds(self):
        o = self.overlay
        o.begin('empty', 100, 'F6')
        o.start_timeline(20, 0)
        o._update_progress()
        self.assertEqual(0, o.progress.value())
        o.begin('song', 100, 'F6', 10)
        o.start_timeline(20, 10)
        self.assertEqual(0, o.elapsed)
        self.clock.now = 999
        o._update_progress()
        self.assertEqual(10, o.elapsed)
        self.assertEqual(1000, o.progress.value())

    def test_real_engine_epoch_speed_long_notes_and_rests(self):
        source = [MidiNote(0, 2, 60), MidiNote(5, 3, 62)]
        for speed in (25, 60, 95, 100, 120, 150):
            with self.subTest(speed=speed):
                clock = FakeClock()
                o = PlaybackOverlay(clock=clock)
                o.set_enabled(False)
                timing = PerformanceTiming.for_speed(speed)
                notes = build_performance_schedule(source, timing)
                sender = FakeInput(clock)
                samples = []
                def wait(seconds):
                    clock.wait(seconds)
                    o._update_progress()
                    samples.append(o.elapsed)
                    return False
                engine = PlaybackEngine(sender, threading.Event(), threading.Lock(), clock=clock, wait=wait)
                try:
                    o.begin('song', speed, 'F6', notes[-1].end)
                    engine.play(notes, timing, diagnose_schedule(notes, timing), lambda _: None,
                                timeline_started=o.start_timeline)
                    self.assertAlmostEqual(8 * 100 / speed, o.duration)
                    self.assertAlmostEqual(o.duration, o.elapsed)
                    self.assertTrue(any(0.5 * 100 / speed < value < 1.5 * 100 / speed for value in samples))
                    self.assertTrue(any(3 * 100 / speed < value < 4 * 100 / speed for value in samples))
                    first_down = next(t for t, action, *_ in sender.events if action == 'down')
                    self.assertAlmostEqual(first_down, o._epoch)
                finally:
                    sender.release_all()
                    o.close()

    def test_ui_wiring_uses_speed_snapshot_and_no_game_input(self):
        with TemporaryDirectory() as temp, patch.dict(os.environ, LOCALAPPDATA=temp), \
                patch.object(MainWindow, '_register_hotkey'), patch.object(MainWindow, '_unregister_hotkey'):
            window = MainWindow()
            try:
                window.speed.set_percent(150)
                with patch.object(window.performer, 'start'):
                    window._start_performance([MidiNote(0, 12, 60)])
                self.assertEqual(8, window.overlay.duration)
                self.assertEqual('-00:08', window.overlay.remaining_label.text())
                with patch.object(window.overlay, '_clock', return_value=102):
                    window.performer.timeline_started.emit(100, 8)
                self.assertEqual(2, window.overlay.elapsed)
                self.assertEqual(250, window.overlay.progress.value())
            finally:
                window.close()
