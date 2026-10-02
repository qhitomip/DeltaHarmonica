import json
import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from delta_harmonica.storage import PreferencesStore, data_directory
from delta_harmonica.ui import MainWindow, TrackSelectionDialog
from test_phase2 import candidate
from delta_harmonica.midi import MidiAnalysis


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.env = patch.dict(os.environ, LOCALAPPDATA=self.temp.name)
        self.env.start()
        self.register = patch.object(MainWindow, '_register_hotkey')
        self.unregister = patch.object(MainWindow, '_unregister_hotkey')
        self.register.start()
        self.unregister.start()
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.register.stop()
        self.unregister.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_dark_default_and_light_choice_survives_restart(self):
        self.assertEqual('dark', self.window.preferences.theme)
        self.assertEqual('切换为浅色', self.window.theme_button.toolTip())
        self.window.theme_button.click()
        self.assertEqual('light', PreferencesStore().load().theme)
        self.assertEqual('切换为深色', self.window.theme_button.accessibleName())
        self.window.close()
        self.window = MainWindow()
        self.assertEqual('light', self.window.preferences.theme)
        self.assertEqual('light', self.window.theme_button.theme)
        self.window.theme_button.click()
        self.assertEqual('dark', PreferencesStore().load().theme)

    def test_live_popup_dialog_and_message_colors_follow_theme_without_changing_playback(self):
        window = self.window
        window.speed.editor.setText('0.92x')
        window.speed.commit_text()
        song_id = window._selected_song().id
        window.progress.setValue(413)
        window.overlay.begin('演奏歌曲', 92, 'F6')
        window.overlay.set_state('正在演奏')
        overlay_style = window.overlay.styleSheet()
        dialog = TrackSelectionDialog(MidiAnalysis((candidate(),), 0, '高', '推荐'), window)
        message = QMessageBox(window)
        dialog.show()
        message.ensurePolished()
        window.speed.show_popup()
        self.app.processEvents()
        dark_editor = window.speed.editor.palette().color(QPalette.ColorRole.Text)
        with patch.object(window.performer, 'stop') as stop, patch.object(window.performer, 'start') as start:
            window.theme_button.click()
            self.app.processEvents()
            stop.assert_not_called()
            start.assert_not_called()
        self.assertEqual(song_id, window._selected_song().id)
        self.assertEqual(92, window.speed.percent)
        self.assertEqual(413, window.progress.value())
        self.assertEqual('正在演奏', window.overlay.state_label.text())
        self.assertEqual(overlay_style, window.overlay.styleSheet())
        self.assertGreater(dark_editor.lightness(), 180)
        for widget, role in ((window.speed.editor, QPalette.ColorRole.Text),
                             (dialog.table, QPalette.ColorRole.Text), (message, QPalette.ColorRole.WindowText)):
            self.assertLess(widget.palette().color(role).lightness(), 120)
        self.assertLess(window.countdown.palette().color(QPalette.ColorRole.Text).lightness(), 120)
        window.theme_button.click()
        self.app.processEvents()
        self.assertGreater(dialog.table.palette().color(QPalette.ColorRole.Text).lightness(), 180)
        window.speed.popup.hide()
        message.close()
        dialog.reject()

    def test_unknown_preference_uses_dark_and_failed_save_is_visible(self):
        self.window.preferences_store.save(self.window.preferences)
        path = data_directory() / 'preferences.json'
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload['theme'] = 'unknown'
        path.write_text(json.dumps(payload), encoding='utf-8')
        self.assertEqual('dark', PreferencesStore().load().theme)
        with patch.object(self.window.preferences_store, 'save', side_effect=OSError('disk full')):
            self.window.theme_button.click()
        self.assertEqual('light', self.window.theme_button.theme)
        self.assertIn('未能保存', self.window.status_label.text())
