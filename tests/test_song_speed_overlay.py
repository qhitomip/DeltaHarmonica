from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from delta_harmonica.overlay import PlaybackOverlay
from delta_harmonica.speed_control import SpeedControl
from delta_harmonica.presets import PRESETS
from delta_harmonica.settings import SPEED_OPTIONS
from delta_harmonica.storage import MidiLibrary, data_directory
from delta_harmonica.ui import MainWindow
from delta_harmonica.performer import PerformanceTiming, build_performance_schedule
from delta_harmonica.midi import MidiNote
from test_midi_import import write_midi


class SongSpeedOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=TemporaryDirectory()
        self.env=patch.dict(os.environ,LOCALAPPDATA=self.temp.name)
        self.env.start()

    def tearDown(self):
        self.app.processEvents();self.env.stop();self.temp.cleanup()

    def test_preset_name_swap_keeps_phrases_and_authoritative_saved_names(self):
        self.assertEqual(['夜莺 · 佐拉任务片段','守望 · 老乔任务片段'],[p.title for p in PRESETS[:2]])
        self.assertEqual(['7676354','5123543123'],[''.join(str(n[0]) for n in p.phrase) for p in PRESETS[:2]])
        library=MidiLibrary()
        song=replace(library.songs[0],title='stale label',speed_percent=92)
        library.update(song)
        loaded=MidiLibrary().songs[0]
        self.assertEqual(PRESETS[0].title,loaded.title)
        self.assertEqual(92,loaded.speed_percent)
        window=MainWindow()
        try:
            window._select_song('builtin:poxiao')
            self.assertIn('先学会前三首',window.song_hint.text())
            self.assertIn('风声未止',window.song_hint.text())
        finally:window.close()

    def test_custom_speed_validation_and_entire_range_timing(self):
        speed=SpeedControl();changes=[];errors=[]
        speed.speed_changed.connect(changes.append);speed.invalid_input.connect(errors.append)
        for text,expected in [('0.92x',92),('0.25',25),('1.50×',150),('1',100)]:
            speed.editor.setText(text);speed.commit_text();self.assertEqual(expected,speed.percent)
        for invalid in ('', '0.24', '1.51', 'NaN', 'inf', '1.001'):
            speed.editor.setText(invalid);speed.commit_text();self.assertEqual(100,speed.percent)
        self.assertEqual(6,len(errors))
        for value in [p for _,p in SPEED_OPTIONS]+[92,137,149]:
            source=[MidiNote(0,.2,60),MidiNote(.2,.8,62)]
            result=build_performance_schedule(source,PerformanceTiming.for_speed(value))
            self.assertAlmostEqual(.2*100/value,result[1].start)
            self.assertAlmostEqual(100/value,result[-1].end)
        self.assertEqual([92,25,150,100],changes)
        speed.close()

    def test_song_speeds_survive_restart_reconversion_and_independent_presets(self):
        path=Path(self.temp.name)/'song.mid';write_midi(path)
        window=MainWindow()
        try:
            with patch('delta_harmonica.ui.TrackSelectionDialog.exec',return_value=1):
                window._import_files([str(path)])
                song_id=window._selected_song().id
                window.speed.editor.setText('0.92x');window.speed.commit_text()
                window._convert_selected()
            window._select_song('builtin:poxiao')
            window.speed.editor.setText('1.37x');window.speed.commit_text()
            window._select_song(song_id)
            self.assertEqual(92,window.speed.percent)
        finally:window.close()
        again=MainWindow()
        try:
            again._select_song(song_id);self.assertEqual(92,again.speed.percent)
            again._select_song('builtin:poxiao');self.assertEqual(137,again.speed.percent)
            again._select_song('builtin:fengqi');self.assertEqual(100,again.speed.percent)
            with patch.object(again.library,'update',side_effect=OSError('disk full')):
                again.speed.editor.setText('0.8x');again.speed.commit_text()
                self.assertEqual(100,again.speed.percent)
                self.assertIn('未能保存',again.status_label.text())
        finally:again.close()

    def test_overlay_no_focus_clickthrough_snapshot_and_lifecycle(self):
        overlay=PlaybackOverlay()
        try:
            for flag in (Qt.WindowType.WindowTransparentForInput,Qt.WindowType.WindowDoesNotAcceptFocus,
                         Qt.WindowType.WindowStaysOnTopHint):
                self.assertTrue(overlay.windowFlags() & flag)
            self.assertTrue(overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
            overlay.begin('example',92,'F6');overlay.set_state('3 秒后开始')
            self.assertIn('3 秒',overlay.state_label.text())
            self.assertIn('0.92x',overlay.detail_label.text())
            overlay.set_enabled(False);self.assertFalse(overlay.isVisible())
            overlay.set_enabled(True);self.assertTrue(overlay.isVisible())
            overlay.set_state('演奏完成');self.assertTrue(overlay.hide_timer.isActive())
            overlay.begin('new',150,'F7');self.assertFalse(overlay.hide_timer.isActive())
            self.assertEqual('new',overlay.song_title)
            overlay.failed();self.assertIn('查看原因',overlay.detail_label.text())
            overlay._dismiss();self.assertFalse(overlay.isVisible())
            overlay.set_enabled(True);self.assertFalse(overlay.isVisible())
        finally:overlay.close()

    def test_overlay_setting_persists_and_close_cleans_window(self):
        window=MainWindow()
        window.overlay_toggle.setChecked(False)
        window.overlay.begin('example',100,'F6')
        self.assertFalse(window.overlay.isVisible())
        window.close()
        payload=json.loads((data_directory()/'preferences.json').read_text(encoding='utf-8'))
        self.assertNotIn('speed_percent',payload)
        again=MainWindow()
        self.assertFalse(again.overlay_toggle.isChecked())
        again.close()
