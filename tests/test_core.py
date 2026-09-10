from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import mido

from delta_harmonica.game_io import NOTE_MAP, ToneBand
from delta_harmonica.midi import MidiConverter, MidiNote, adapt_midi_to_game_range
from delta_harmonica.storage import validate_notes


class PitchMapTests(unittest.TestCase):
    def test_has_28_unique_playable_pitches(self) -> None:
        self.assertEqual(28, len(NOTE_MAP))
        self.assertEqual(48, min(NOTE_MAP))
        self.assertEqual(84, max(NOTE_MAP))

    def test_prefers_normal_keys_for_duplicate_pitches(self) -> None:
        self.assertEqual(ToneBand.NATURAL, NOTE_MAP[60].band)
        self.assertEqual(ToneBand.NATURAL, NOTE_MAP[65].band)
        self.assertEqual(ToneBand.NATURAL, NOTE_MAP[72].band)

    def test_known_accidentals_use_half_tone_modifier(self) -> None:
        for midi in (61, 63, 66, 68, 70, 73):
            self.assertEqual(ToneBand.SEMITONE, NOTE_MAP[midi].band)


class ScoreTests(unittest.TestCase):
    def test_rejects_overlapping_notes(self) -> None:
        with self.assertRaises(ValueError):
            validate_notes([
                MidiNote(start=0.0, duration=1.0, midi=60),
                MidiNote(start=0.5, duration=1.0, midi=62),
            ])


class MidiConversionTests(unittest.TestCase):
    def test_adapts_every_pitch_without_changing_pitch_classes(self) -> None:
        source = [
            MidiNote(start=0.0, duration=0.2, midi=35),
            MidiNote(start=0.3, duration=0.2, midi=78),
            MidiNote(start=0.6, duration=0.2, midi=91),
        ]
        adapted, transpose = adapt_midi_to_game_range(source)
        self.assertTrue(adapted)
        self.assertTrue(all(note.midi in NOTE_MAP for note in adapted))
        self.assertEqual(
            [(note.midi + transpose) % 12 for note in source],
            [note.midi % 12 for note in adapted],
        )
        validate_notes(adapted)

    def test_selects_named_melody_track_and_preserves_repeated_notes(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "song.mid"
            midi = mido.MidiFile(type=1, ticks_per_beat=480)

            tempo = mido.MidiTrack()
            tempo.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
            midi.tracks.append(tempo)

            bass = mido.MidiTrack()
            bass.append(mido.MetaMessage("track_name", name="Bass", time=0))
            for pitch in (36, 38, 40, 41, 43, 41):
                bass.append(mido.Message("note_on", channel=0, note=pitch, velocity=90, time=0))
                bass.append(mido.Message("note_off", channel=0, note=pitch, velocity=0, time=480))
            midi.tracks.append(bass)

            melody = mido.MidiTrack()
            melody.append(mido.MetaMessage("track_name", name="Lead Melody", time=0))
            for pitch in (72, 72, 74, 76, 77, 79):
                melody.append(mido.Message("note_on", channel=1, note=pitch, velocity=100, time=0))
                melody.append(mido.Message("note_off", channel=1, note=pitch, velocity=0, time=240))
            midi.tracks.append(melody)
            midi.save(path)

            result = MidiConverter().convert(path)

        self.assertIn("Lead Melody", result.track_name)
        self.assertEqual(6, result.source_note_count)
        self.assertEqual(6, len(result.notes))
        self.assertEqual(result.notes[0].midi, result.notes[1].midi)
        self.assertAlmostEqual(0.25, result.notes[0].duration, places=3)
        self.assertTrue(all(note.midi in NOTE_MAP for note in result.notes))

    def test_uses_top_note_when_a_track_contains_chords(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "chords.mid"
            midi = mido.MidiFile(type=0, ticks_per_beat=480)
            track = mido.MidiTrack()
            track.append(mido.MetaMessage("track_name", name="Piano Melody", time=0))
            for chord in ((60, 64, 67), (62, 65, 69), (64, 67, 71)):
                for pitch in chord:
                    track.append(mido.Message("note_on", channel=0, note=pitch, velocity=90, time=0))
                track.append(mido.Message("note_off", channel=0, note=chord[0], velocity=0, time=480))
                for pitch in chord[1:]:
                    track.append(mido.Message("note_off", channel=0, note=pitch, velocity=0, time=0))
            midi.tracks.append(track)
            midi.save(path)

            result = MidiConverter().convert(path)

        self.assertEqual(3, len(result.notes))
        intervals = [
            (current.midi - previous.midi) % 12
            for previous, current in zip(result.notes, result.notes[1:])
        ]
        self.assertEqual([2, 2], intervals)


if __name__ == "__main__":
    unittest.main()
