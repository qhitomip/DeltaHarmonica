from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication
from delta_harmonica.audition import MidiAudition, candidate_preview_notes
from delta_harmonica.game_io import NOTE_MAP, ToneBand
from delta_harmonica.midi import MidiNote, MidiSourceNote, MidiCandidate, MidiAnalysis
from delta_harmonica.performer import PlaybackEngine, PerformanceTiming, build_performance_schedule, diagnose_schedule, resolve_keys
from delta_harmonica.presets import PRESETS
from delta_harmonica.storage import MidiLibrary, data_directory, PreferencesStore
from delta_harmonica.ui import MainWindow, TrackSelectionDialog
from test_playback import FakeClock, FakeInput


class FakeOutput:
    def __init__(self):
        self.messages = []
        self.closed = False
        self.fail_send = False
        self.fail_close = False

    def send(self, message):
        if self.fail_send:
            raise OSError('fake output failure')
        self.messages.append(message)

    def close(self):
        if self.fail_close:
            raise OSError('fake cleanup failure')
        self.closed = True


def candidate(pitch=60):
    return MidiCandidate(0, 'Melody', 0,
                         (MidiSourceNote(0, 480, 4, 5, pitch, 80, 0),), 1)


class PresetTests(unittest.TestCase):
    def test_quest_sequences_keep_low_high_and_long_note(self):
        self.assertEqual(['7676354', '5123543123', '6712171', '76367671434'],
                         [''.join(str(n[0]) for n in p.phrase) for p in PRESETS])
        self.assertTrue(PRESETS[0].phrase[3][2])
        self.assertEqual(ToneBand.LOW, PRESETS[1].phrase[0][1])
        self.assertEqual([ToneBand.LOW]*2 + [ToneBand.NATURAL]*3 + [ToneBand.LOW, ToneBand.NATURAL],
                         [n[1] for n in PRESETS[2].phrase])
        self.assertEqual([ToneBand.HIGH]*4, [n[1] for n in PRESETS[3].phrase[-4:]])

    def test_all_presets_keep_explicit_keys_and_timeline_at_each_speed(self):
        for preset in PRESETS:
            for speed in (25, 50, 75, 100, 125, 150):
                with self.subTest(preset=preset.id, speed=speed):
                    notes, keys = preset.performance()
                    clock, cancel = FakeClock(), threading.Event()
                    sender = FakeInput(clock)
                    timing = PerformanceTiming.for_speed(speed)
                    scheduled = build_performance_schedule(notes, timing, keys)
                    diagnostics = diagnose_schedule(scheduled, timing, keys)
                    engine = PlaybackEngine(sender, cancel, threading.Lock(), clock=clock, wait=clock.wait)
                    engine.play(scheduled, timing, diagnostics, lambda _: None, keys)
                    sender.release_all()
                    downs = [e for e in sender.events if e[1] == 'down']
                    self.assertEqual([k.virtual_key for k in keys], [e[2] for e in downs])
                    for note, event in zip(notes, downs):
                        self.assertAlmostEqual(note.start*100/speed + timing.modifier_lead_seconds, event[0])
                    self.assertFalse(sender.held)
                    self.assertEqual(len(notes), diagnostics.played_notes)
                    self.assertEqual(0, diagnostics.short_modifier_leads)
        notes, keys = PRESETS[3].performance()
        self.assertNotEqual(NOTE_MAP[notes[7].midi], keys[7])
        self.assertEqual((ToneBand.HIGH, ord('Z')), (keys[7].band, keys[7].virtual_key))
        with self.assertRaises(ValueError):
            resolve_keys(notes, keys[:-1])

    def test_defaults_do_not_duplicate_or_replace_existing_library(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, LOCALAPPDATA=directory):
            midi = Path(directory) / 'old-song.mid'
            midi.write_bytes(b'MThd')
            library = MidiLibrary()
            songs, errors = library.import_files([str(midi)])
            self.assertFalse(errors)
            songs[0].track_index, songs[0].channel = 2, 1
            songs[0].converted_path = 'existing-result.json'
            library.update(songs[0])
            for _ in range(3):
                library = MidiLibrary()
                self.assertEqual(5, len(library.songs))
                self.assertEqual(4, sum(song.is_builtin for song in library.songs))
                self.assertEqual(2, library.songs[0].track_index)
                self.assertEqual('existing-result.json', library.songs[0].converted_path)
            payload = json.loads((data_directory() / 'library.json').read_text(encoding='utf-8'))
            self.assertEqual(5, len(payload['songs']))
            self.assertTrue({'delay_seconds', 'playback_mode'}.isdisjoint(payload['songs'][0]))


class AuditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.clock, self.output = FakeClock(), FakeOutput()
        self.player = MidiAudition(output_factory=lambda: self.output, clock=self.clock)
        self.errors, self.states = [], []
        self.player.failed.connect(self.errors.append)
        self.player.state_changed.connect(self.states.append)

    def tearDown(self):
        self.output.fail_close = False
        self.player.stop()

    def advance(self, now):
        self.clock.now = now
        self.player._tick()

    def test_speed_snapshot_and_late_tick_skip_expired_notes(self):
        self.player.start([MidiNote(4, .1, 60), MidiNote(4.2, .1, 62), MidiNote(4.4, 1, 64)], 60)
        self.assertEqual(0x90, self.output.messages[0] & 255)
        self.advance(1)
        pitches = [(message >> 8) & 127 for message in self.output.messages if message & 255 == 0x90]
        self.assertEqual([60, 64], pitches)
        self.advance(1.4/0.6 + .001)
        self.assertTrue(self.output.closed)
        self.assertFalse(self.player.is_running)
        self.assertEqual('试听完成', self.states[-1])

    def test_overlapping_same_pitch_keeps_sound_until_last_release(self):
        self.player.start([MidiNote(0, 1, 60), MidiNote(.5, 1, 60)])
        self.advance(.5)
        self.advance(1)
        self.assertEqual(1, len(self.output.messages))
        self.advance(1.5)
        self.assertEqual([0x90, 0x80], [m & 255 for m in self.output.messages])

    def test_adjacent_repeated_notes_have_off_before_on(self):
        self.player.start([MidiNote(0, .5, 60), MidiNote(.5, .5, 60)])
        self.advance(.5)
        self.assertEqual([0x90, 0x80, 0x90], [m & 255 for m in self.output.messages])

    def test_stop_prevents_future_notes_and_resets_device(self):
        self.player.start([MidiNote(0, 1, 60), MidiNote(2, 1, 62)])
        before = list(self.output.messages)
        self.player.stop()
        self.advance(2.1)
        self.assertEqual(before, self.output.messages)
        self.assertTrue(self.output.closed)

    def test_output_failure_cleans_up_and_keeps_error(self):
        self.output.fail_send = True
        self.player.start([MidiNote(0, 1, 60)])
        self.assertTrue(self.output.closed)
        self.assertIn('fake output failure', self.errors[-1])
        self.assertFalse(self.player.is_running)

    def test_cleanup_failure_is_visible_and_blocks_device_replacement(self):
        self.player.start([MidiNote(0, 1, 60)])
        self.output.fail_close = True
        self.player.stop()
        self.assertIn('cleanup failure', self.errors[-1])
        self.assertNotEqual('试听已停止', self.states[-1])
        factory = Mock()
        self.player.output_factory = factory
        self.player.start([MidiNote(0, 1, 62)])
        factory.assert_not_called()
        self.assertIs(self.output, self.player.output)

    def test_invalid_notes_and_missing_synth_report_failure(self):
        factory = Mock(side_effect=OSError('no synth'))
        self.player.output_factory = factory
        for notes in ([], [MidiNote(0, 0, 60)], [MidiNote(float('nan'), 1, 60)], [MidiNote(0, 1, 128)]):
            self.player.start(notes)
        factory.assert_not_called()
        self.player.start([MidiNote(0, 1, 60)])
        self.assertEqual('no synth', self.errors[-1])

    def test_source_preview_does_not_adapt_octaves_or_drop_polyphony(self):
        notes = (MidiSourceNote(0, 480, 4, 5, 24, 80, 0), MidiSourceNote(0, 480, 4, 5, 108, 90, 0))
        raw = MidiCandidate(0, 'Piano', 0, notes, 1)
        converted = candidate_preview_notes(raw)
        self.assertEqual([24, 108], [n.midi for n in converted])
        self.assertEqual([0, 0], [n.start for n in converted])


class Phase2UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.env = patch.dict(os.environ, LOCALAPPDATA=self.directory.name)
        self.env.start()
        self.register = patch.object(MainWindow, '_register_hotkey')
        self.unregister = patch.object(MainWindow, '_unregister_hotkey')
        self.register.start()
        self.unregister.start()
        self.window = MainWindow()
        self.output = FakeOutput()
        self.window.audition.output_factory = lambda: self.output
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.unregister.stop()
        self.register.stop()
        self.env.stop()
        self.directory.cleanup()

    def test_changing_songs_restores_each_speed_and_keeps_global_delay(self):
        self.window.speed.preset_buttons[150].click()
        self.window.countdown.setValue(5)
        self.window.table.selectRow(1)
        self.assertEqual(100, self.window.speed.percent)
        self.window.speed.preset_buttons[75].click()
        self.window.table.selectRow(0)
        self.assertEqual(150, self.window.speed.percent)
        self.assertEqual(5, PreferencesStore().load().delay_seconds)
        self.assertFalse(hasattr(self.window, 'playback_mode'))
        self.assertFalse(hasattr(self.window, 'speed_slider'))
        self.assertTrue(self.window.settings_panel.isHidden())
        self.window.settings_button.click()
        self.assertFalse(self.window.settings_panel.isHidden())

    def test_builtin_plays_without_conversion_and_audition_stops_first(self):
        with patch.object(self.window.performer, 'start') as start, patch.object(self.window.converter, 'analyze') as analyze:
            self.window._select_song('builtin:poxiao')
            self.window._toggle_preview()
            self.assertTrue(self.window.audition.is_running)
            start.assert_not_called()
            self.window._start_selected_from_hotkey()
            self.assertTrue(self.output.closed)
            start.assert_called_once()
            keys = start.call_args.kwargs['keys']
            self.assertEqual(ToneBand.HIGH, keys[7].band)
            self.assertEqual(ord('Z'), keys[7].virtual_key)
            analyze.assert_not_called()
        self.assertTrue(self.window.remove_button.isEnabled())
        self.assertFalse(self.window.analyze_button.isEnabled())

    def test_switch_song_and_close_stop_local_sound(self):
        self.window._toggle_preview()
        self.window.table.selectRow(1)
        self.assertTrue(self.output.closed)
        self.assertFalse(self.window.audition.is_running)
        self.output = FakeOutput()
        self.window._toggle_preview()
        self.window.close()
        self.assertTrue(self.output.closed)

    def test_running_preview_keeps_speed_until_restart_and_failure_visible(self):
        self.window._toggle_preview()
        events = list(self.window.audition.events)
        self.window.speed.preset_buttons[150].click()
        self.assertEqual(events, self.window.audition.events)
        self.assertIn('下次开始生效', self.window.pending_settings.text())
        self.output.fail_close = True
        self.window.audition.stop()
        self.assertIn('cleanup failure', self.window.status_label.text())
        self.output.fail_close = False

    def test_track_dialog_preview_stops_on_selection_and_close(self):
        dialog = TrackSelectionDialog(MidiAnalysis((candidate(), candidate(72)), 0, '低', '测试'), self.window)
        output = FakeOutput()
        dialog.preview.output_factory = lambda: output
        dialog._toggle_preview()
        self.assertTrue(dialog.preview.is_running)
        dialog.table.selectRow(1)
        self.assertTrue(output.closed)
        output = FakeOutput()
        dialog._toggle_preview()
        dialog.reject()
        self.assertTrue(output.closed)
        self.assertFalse(dialog.preview.is_running)

    def test_hotkey_edit_updates_quest_instructions(self):
        self.window.hotkey.setCurrentText('F7')
        self.assertIn('F7', self.window.song_hint.text())
        self.assertNotIn('F6', self.window.song_hint.text())


if __name__ == '__main__':
    unittest.main()
