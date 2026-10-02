"""Generate original, deterministic MIDI phrases for phase-one game checks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import mido


def generate(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    # 120 BPM and 1000 ticks/beat make each tick exactly 0.5 ms.
    phrases = {
        '01-repeated-notes': [(60, .25, .25)] * 16,
        '02-long-short': [(p, d, d + .1) for p, d in
                          [(60, 1), (62, .1), (64, .5), (65, .08), (67, 1), (69, .1), (71, .5), (72, .08)]],
        '03-band-switches': [(p, .2, .25) for p in (48, 61, 76, 60, 50, 63, 77, 62) * 2],
        '04-dense-speed': [(p, .04, .04) for p in (60, 60, 62, 64, 65, 67, 69, 71) * 4],
        '05-range-reference': [(p, .3, .45) for p in
                               (48, 50, 52, 53, 55, 57, 59, 60, 61, 62, 63, 64, 65, 66,
                                67, 68, 69, 70, 71, 72, 73, 74, 76, 77, 79, 81, 83, 84)],
    }
    manifest = []
    for name, phrase in phrases.items():
        midi = mido.MidiFile(type=1, ticks_per_beat=1000)
        meta = mido.MidiTrack()
        meta.append(mido.MetaMessage('set_tempo', tempo=500000))
        midi.tracks.append(meta)
        track = mido.MidiTrack()
        track.append(mido.MetaMessage('track_name', name='Lead Melody - Phase 1'))
        track.append(mido.Message('program_change', program=22, channel=0))
        midi.tracks.append(track)
        events = []
        pending = 0
        tick = 0
        for pitch, duration, slot in phrase:
            duration_ticks = round(duration * 2000)
            slot_ticks = round(slot * 2000)
            track.append(mido.Message('note_on', note=pitch, velocity=90, time=pending))
            track.append(mido.Message('note_off', note=pitch, velocity=0, time=duration_ticks))
            events.append({'start': tick / 2000, 'duration': duration_ticks / 2000, 'midi': pitch})
            pending = slot_ticks - duration_ticks
            tick += slot_ticks
        midi.save(destination / f'{name}.mid')
        length = events[-1]['start'] + events[-1]['duration']
        manifest.append({'file': f'{name}.mid', 'notes': len(events), 'seconds_at_100': length,
                         'seconds_by_speed': {str(s): round(length * 100 / s, 6) for s in (60, 95, 100, 120)},
                         'source_notes': events})
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Generated {len(manifest)} original MIDI fixtures in {destination}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    generate(parser.parse_args().destination)
