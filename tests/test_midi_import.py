import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import mido
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from delta_harmonica.storage import MidiLibrary, Preferences, PreferencesStore, data_directory, load_performance
from delta_harmonica.ui import DropZone, IMPORT_FILTER, MainWindow


def write_midi(path):
    midi = mido.MidiFile()
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage('track_name', name='Melody'))
    for pitch in (60, 62, 64):
        track.append(mido.Message('note_on', note=pitch, velocity=80))
        track.append(mido.Message('note_off', note=pitch, time=480))
    midi.save(path)


class MidiImportTests(unittest.TestCase):
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

    def test_library_accepts_midi_but_rejects_audio_and_keeps_originals(self):
        midi = self.root/'test.MID'
        write_midi(midi)
        others = [self.root/'test.mp3', self.root/'test.wav', self.root/'test.flac']
        for path in others:
            path.write_bytes(b'original file')
        library = MidiLibrary()
        imported, errors = library.import_files([str(midi), *map(str, others)])
        self.assertEqual([str(midi)], [song.source_path for song in imported])
        self.assertEqual(3, len(errors))
        self.assertTrue(all('仅支持 MIDI' in error for error in errors))
        self.assertEqual(5, len(MidiLibrary().songs))
        for path in others:
            self.assertEqual(b'original file', path.read_bytes())

    def test_global_preferences_roundtrip_and_no_audio_fields(self):
        store = PreferencesStore()
        self.assertEqual(Preferences(), store.load())
        changed = Preferences(delay_seconds=3, hotkey='F7', overlay_enabled=False)
        store.save(changed)
        self.assertEqual(changed, store.load())
        payload = json.loads((data_directory()/'preferences.json').read_text(encoding='utf-8'))
        self.assertEqual({'format','delay_seconds','hotkey','overlay_enabled','theme'}, set(payload))

    def test_old_conversion_library_is_not_migrated_or_modified(self):
        path = data_directory()/'library.json'
        payload = {'format':'delta-harmonica-library-1', 'songs':[]}
        original = json.dumps(payload)
        path.write_text(original, encoding='utf-8')
        self.assertEqual(4, len(MidiLibrary().songs))
        self.assertEqual(original, path.read_text(encoding='utf-8'))

    def test_drop_rejects_audio_and_emits_only_local_midi(self):
        drop = DropZone()
        emitted = []
        drop.files_dropped.connect(emitted.append)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.root/'song.mp3'))])
        enter = QDragEnterEvent(QPoint(10,10), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        enter.ignore()
        drop.dragEnterEvent(enter)
        self.assertFalse(enter.isAccepted())
        midi = self.root/'song.MIDI'
        mime.setUrls([QUrl.fromLocalFile(str(midi)), QUrl.fromLocalFile(str(self.root/'song.wav')),
                      QUrl('https://example.org/song.mid')])
        event = QDropEvent(QPointF(10,10), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        drop.dropEvent(event)
        self.assertEqual([[midi]], [[Path(path) for path in paths] for paths in emitted])

    def test_file_picker_import_converts_midi_for_existing_playback_path(self):
        path = self.root/'melody.mid'
        write_midi(path)
        window = MainWindow()
        try:
            with patch('delta_harmonica.ui.QFileDialog.getOpenFileNames', return_value=([str(path)], IMPORT_FILTER)) as picker:
                window._choose_files()
            self.assertEqual('MIDI 曲谱 (*.mid *.midi)', picker.call_args.args[-1])
            selected = window._selected_song()
            notes = load_performance(selected.converted_path)
            self.assertEqual([60,62,64], [note.midi for note in notes])
            with patch.object(window.performer, 'start') as start:
                window._start_selected_from_hotkey()
            self.assertEqual(notes, start.call_args.args[0])
            self.assertEqual(3, start.call_args.args[1])
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
