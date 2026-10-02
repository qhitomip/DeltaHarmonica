import ctypes
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from PySide6.QtWidgets import QApplication, QDialog
from delta_harmonica.hotkey import F12Hotkey, KeyEvent
from delta_harmonica.settings import HOTKEYS, SPEED_OPTIONS
from delta_harmonica.storage import MidiLibrary, Preferences, PreferencesStore, data_directory
from delta_harmonica.ui import MainWindow, TrackSelectionDialog
from test_midi_import import write_midi
from test_phase2 import FakeOutput, candidate
from delta_harmonica.midi import MidiAnalysis


class UiRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.env = patch.dict(os.environ, LOCALAPPDATA=self.temp.name)
        self.env.start()
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.env.stop()
        self.temp.cleanup()

    def test_defaults_all_hotkeys_and_six_speeds_roundtrip(self):
        self.assertEqual((3, 'F6', 100), (self.window.countdown.value(), self.window.hotkey.currentText(), self.window.speed.percent))
        self.assertEqual([f'F{i}' for i in range(1, 13)], list(HOTKEYS))
        for hotkey in HOTKEYS:
            pref = Preferences(hotkey=hotkey, overlay_enabled=False)
            PreferencesStore().save(pref)
            self.assertEqual(pref, PreferencesStore().load())
        self.assertEqual([value for _, value in SPEED_OPTIONS],
                         list(self.window.speed.preset_buttons))
        payload = json.loads((data_directory()/'preferences.json').read_text(encoding='utf-8'))
        self.assertNotIn('playback_mode', payload)

    def test_removed_presets_stay_removed_including_empty_library(self):
        for preset in self.window.library.songs:
            self.window._select_song(preset.id)
            self.assertTrue(self.window.remove_button.isEnabled())
            self.window._remove_selected()
        self.assertEqual([], MidiLibrary().songs)
        self.assertEqual(0, self.window.table.rowCount())
        self.assertFalse(self.window.preview_button.isEnabled())

    def test_every_import_requires_confirmation_and_cancel_does_not_convert(self):
        paths = []
        for name in ('first', 'second'):
            path = Path(self.temp.name)/f'{name}.mid'
            write_midi(path)
            paths.append(str(path))
        decisions = [QDialog.DialogCode.Accepted, QDialog.DialogCode.Rejected]
        with patch.object(TrackSelectionDialog, 'exec', side_effect=decisions) as dialog:
            self.window._import_files(paths)
        self.assertEqual(2, dialog.call_count)
        songs = {song.title: song for song in self.window.library.songs if not song.is_builtin}
        self.assertTrue(Path(songs['first'].converted_path).is_file())
        self.assertIsNone(songs['second'].converted_path)
        self.assertEqual('等待选择音轨', songs['second'].status)

    def test_each_track_has_audition_and_switch_closes_previous_sound(self):
        dialog = TrackSelectionDialog(MidiAnalysis((candidate(), candidate(72)), 0, '高', '推荐'))
        outputs = []
        def factory():
            output = FakeOutput()
            outputs.append(output)
            return output
        dialog.preview.output_factory = factory
        try:
            dialog.table.cellWidget(0, 9).click()
            self.assertTrue(dialog.preview.is_running)
            dialog.table.cellWidget(1, 9).click()
            self.assertTrue(outputs[0].closed)
            self.assertEqual(72, dialog.selected_candidate().notes[0].midi)
            self.assertTrue(dialog.preview.is_running)
            dialog.reject()
            self.assertTrue(outputs[-1].closed)
        finally:
            dialog.preview.stop()

    def test_midishow_search_encodes_user_text_and_has_no_other_provider(self):
        with patch('delta_harmonica.ui.QDesktopServices.openUrl', return_value=True) as browser:
            self.window.midi_search.setText('加勒比 & F#')
            self.window._search_midishow()
            url = urlparse(browser.call_args.args[0].toString())
            self.assertEqual('www.midishow.com', url.hostname)
            self.assertEqual(['加勒比 & F#'], parse_qs(url.query)['q'])
            self.window.midi_search.clear()
            self.window._search_midishow()
            self.assertEqual('https://www.midishow.com/', browser.call_args.args[0].toString())
        self.assertFalse(hasattr(self.window, 'midify_button'))
        self.assertFalse(hasattr(self.window, 'midicloud_button'))

    def test_f12_uses_hook_instead_of_reserved_registration(self):
        self.window.preferences.hotkey = 'F12'
        with patch.object(self.window._f12_hotkey, 'register', return_value=True) as hook, \
                patch('delta_harmonica.ui.ctypes.windll.user32.RegisterHotKey') as native:
            self.window._register_hotkey()
            hook.assert_called_once()
            native.assert_not_called()
        self.window._hotkey_registered = False

    def test_f12_no_repeat_filter_release_and_stale_queued_event(self):
        hook = F12Hotkey()
        hook.user32 = Mock()
        hook.user32.CallNextHookEx.return_value = 9
        hook.handle = 1
        fired = []
        hook.pressed.connect(fired.append)
        event = KeyEvent(vkCode=0x7B)
        for _ in range(4):
            self.assertEqual(1, hook._event(0, 0x100, ctypes.addressof(event)))
        self.assertEqual(1, len(fired))
        hook._event(0, 0x101, ctypes.addressof(event))
        hook._event(0, 0x100, ctypes.addressof(event))
        self.assertEqual(2, len(fired))
        event.vkCode = 0x41
        self.assertEqual(9, hook._event(0, 0x100, ctypes.addressof(event)))
        hook.close()
        self.assertFalse(hook.active)
        self.window.preferences.hotkey = 'F12'
        self.window._hotkey_registered = True
        with patch.object(self.window, '_toggle_performance') as toggle:
            self.window._f12_pressed(self.window._f12_hotkey.generation-1)
            toggle.assert_not_called()
            self.window._f12_pressed(self.window._f12_hotkey.generation)
            toggle.assert_called_once()
        self.window._hotkey_registered = False
