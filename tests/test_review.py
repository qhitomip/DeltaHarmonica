import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import mido
from PySide6.QtWidgets import QApplication

from delta_harmonica.midi import MidiConverter, MidiNote
from delta_harmonica.storage import MidiLibrary, load_performance, validate_notes
from delta_harmonica.ui import MainWindow
from test_midi_import import write_midi


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.env = patch.dict(os.environ, LOCALAPPDATA=self.directory.name)
        self.env.start()
        self.dialog_patch = patch('delta_harmonica.ui.TrackSelectionDialog.exec', return_value=1)
        self.dialog_patch.start()

    def tearDown(self):
        self.app.processEvents()
        self.dialog_patch.stop()
        self.env.stop()
        self.directory.cleanup()

    def test_one_and_two_note_midi_are_playable(self):
        for count in (1, 2):
            midi = mido.MidiFile()
            track = mido.MidiTrack()
            midi.tracks.append(track)
            for pitch in (60, 62)[:count]:
                track.append(mido.Message('note_on', note=pitch, velocity=80))
                track.append(mido.Message('note_off', note=pitch, time=480))
            path = self.root / 'short.mid'
            midi.save(path)
            result = MidiConverter().convert(path)
            self.assertEqual(count, len(result.notes))

    def test_type_two_independent_sequences_are_rejected(self):
        path = self.root / 'sequences.mid'
        midi = mido.MidiFile(type=2)
        midi.tracks.append(mido.MidiTrack())
        midi.save(path)
        with self.assertRaisesRegex(ValueError, 'Type 2'):
            MidiConverter().analyze(path)

    def test_analyzed_snapshot_survives_source_removal(self):
        path = self.root / 'melody.mid'
        write_midi(path)
        converter = MidiConverter()
        expected = converter.convert(path)
        analysis = converter.analyze(path)
        path.unlink()
        self.assertEqual(expected, converter.convert_analysis(analysis))

    def test_invalid_scores_rejected_before_preview_or_input(self):
        for notes in ([], [MidiNote(float('nan'), 1, 60)],
                      [MidiNote(0, float('inf'), 60)], [MidiNote(0, 1, 49)],
                      [MidiNote(0, 1, 60), MidiNote(.9995, 1, 62)]):
            with self.subTest(notes=notes), self.assertRaises(ValueError):
                validate_notes(notes)
        path = self.root / 'score.json'
        for payload in ([], None, {'format': 'delta-harmonica-score-1', 'notes': None},
                        {'format': 'delta-harmonica-score-1', 'notes': [None]}):
            path.write_text(json.dumps(payload), encoding='utf-8')
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                load_performance(path)

    def test_failed_library_save_does_not_import_or_remove_in_memory(self):
        path = self.root / 'melody.mid'
        write_midi(path)
        library = MidiLibrary()
        with patch('delta_harmonica.storage._write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                library.import_files([str(path)])
        self.assertEqual(4, len(library.songs))
        songs, _ = library.import_files([str(path)])
        with patch('delta_harmonica.storage._write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                library.remove(songs[0].id)
        self.assertEqual(5, len(library.songs))
        self.assertEqual(5, len(MidiLibrary().songs))

    def test_ui_reuses_analysis_and_reports_invalid_import(self):
        path = self.root / 'melody.mid'
        write_midi(path)
        broken = self.root / 'broken.mid'
        broken.write_bytes(b'not a MIDI')
        window = MainWindow()
        try:
            with patch.object(window.converter, 'analyze', wraps=window.converter.analyze) as analyze:
                window._import_files([str(path)])
                self.assertEqual(1, analyze.call_count)
            with patch('delta_harmonica.ui.QMessageBox.information'):
                window._import_files([str(broken)])
            failed = next(s for s in MidiLibrary().songs if s.source_path == str(broken))
            self.assertEqual('转换失败', failed.status)
        finally:
            window.close()

    def test_settings_write_error_is_visible_and_keeps_session_value(self):
        window = MainWindow()
        try:
            with patch.object(window.preferences_store, 'save', side_effect=OSError('disk full')):
                window.countdown.setValue(5)
                self.assertEqual(5, window.preferences.delay_seconds)
                self.assertIn('未能保存', window.status_label.text())
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
