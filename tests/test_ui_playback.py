from __future__ import annotations

import ctypes
import os
import time
import unittest
from ctypes import wintypes
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from delta_harmonica.midi import MidiNote
from delta_harmonica.performer import MidiPerformer
from delta_harmonica.ui import MainWindow, HOTKEY_ID, MOD_NOREPEAT, WM_HOTKEY
from test_playback import FakeInput


class PlaybackUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.env = patch.dict(os.environ, {'LOCALAPPDATA': self.directory.name})
        self.env.start()
        self.register = patch('delta_harmonica.ui.ctypes.windll.user32.RegisterHotKey', return_value=1)
        self.unregister = patch('delta_harmonica.ui.ctypes.windll.user32.UnregisterHotKey', return_value=1)
        self.register_mock = self.register.start()
        self.unregister.start()
        self.sender = FakeInput()
        self.factory = patch('delta_harmonica.ui.MidiPerformer',
                             side_effect=lambda: MidiPerformer(input_factory=lambda: self.sender))
        self.factory.start()
        self.window = MainWindow()
        self.window.countdown.setValue(0)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.sender.fail_up = False
        self.window.performer.stop()
        self.pump_until(lambda: not self.window.performer.is_running)
        self.window.close()
        self.app.processEvents()
        self.factory.stop()
        self.unregister.stop()
        self.register.stop()
        self.env.stop()
        self.directory.cleanup()

    def pump_until(self, predicate, timeout=2):
        deadline = time.perf_counter() + timeout
        while not predicate() and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(.001)
        self.assertTrue(predicate())

    def hotkey(self):
        message = wintypes.MSG()
        message.message, message.wParam = WM_HOTKEY, HOTKEY_ID
        self.window.nativeEvent(b'windows_generic_MSG', ctypes.addressof(message))

    def test_hotkey_registers_windows_no_repeat_and_toggles_start_stop(self):
        self.assertEqual(MOD_NOREPEAT, self.register_mock.call_args.args[2])
        self.assertEqual('F6', self.window.hotkey.currentText())
        self.window._start_selected_from_hotkey = Mock(
            side_effect=lambda: self.window._start_performance([MidiNote(0, 2, 48)]))
        self.hotkey()
        self.pump_until(lambda: bool(self.sender.held))
        self.hotkey()
        self.pump_until(lambda: not self.window.performer.is_running)
        self.assertFalse(self.sender.held)
        self.window._start_selected_from_hotkey.assert_called_once()

    def test_speed_change_is_saved_but_current_session_keeps_snapshot(self):
        self.window.speed.preset_buttons[100].click()
        self.window._start_performance([MidiNote(0, 2, 60)])
        self.window.speed.preset_buttons[150].click()
        self.assertEqual(100, self.window.performer.diagnostics.speed_percent)
        self.assertEqual(150, self.window._selected_song().speed_percent)
        self.assertIn('下次开始生效', self.window.pending_settings.text())

    def test_close_waits_for_worker_cleanup(self):
        self.window._start_performance([MidiNote(0, 2, 48)])
        self.pump_until(lambda: bool(self.sender.held))
        self.window.close()
        self.assertTrue(self.window.isVisible())
        self.pump_until(lambda: not self.window.isVisible())
        self.assertFalse(self.window.performer.is_running)
        self.assertFalse(self.sender.held)

    def test_cleanup_failure_keeps_window_and_error_visible(self):
        self.window._start_performance([MidiNote(0, 2, 48)])
        self.pump_until(lambda: bool(self.sender.held))
        self.sender.fail_up = True
        self.window.close()
        self.pump_until(lambda: not self.window.performer.is_running)
        self.assertTrue(self.window.isVisible())
        self.assertIn('释放按键失败', self.window.status_label.text())

    def test_hotkey_conflict_and_change_are_visible(self):
        self.register_mock.return_value = 0
        self.window.hotkey.setCurrentText('F7')
        self.assertIn('不可用', self.window.ready_badge.text())
        self.assertIn('占用', self.window.status_label.text())

    def test_zero_delay_and_pending_countdown_cancel(self):
        self.assertEqual(0, self.window.countdown.value())
        self.window.countdown.setValue(3)
        self.window._start_performance([MidiNote(0, .2, 60)])
        self.assertFalse(self.window.table.isEnabled())
        self.assertFalse(self.window.hotkey.isEnabled())
        self.hotkey()
        self.pump_until(lambda: not self.window.performer.is_running)
        self.assertFalse(any(e[1] == 'down' for e in self.sender.events))
        self.assertTrue(self.window.table.isEnabled())
        self.assertTrue(self.window.hotkey.isEnabled())


if __name__ == '__main__':
    unittest.main()
