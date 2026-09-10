from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .game_io import NOTE_MAP, ToneBand


@dataclass(frozen=True, slots=True)
class MidiNote:
    start: float
    duration: float
    midi: int
    confidence: float = 1.0

    @property
    def end(self) -> float:
        return self.start + self.duration

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MidiNote":
        return cls(
            start=float(value["start"]),
            duration=float(value["duration"]),
            midi=int(value["midi"]),
            confidence=float(value.get("confidence", 1.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MidiSourceNote:
    start_tick: int
    end_tick: int
    start: float
    end: float
    midi: int
    velocity: int
    channel: int


@dataclass(frozen=True, slots=True)
class MidiCandidate:
    track_index: int
    track_name: str
    channel: int
    notes: tuple[MidiSourceNote, ...]
    score: float

    @property
    def display_name(self) -> str:
        return f"{self.track_name} · 通道 {self.channel + 1}"


@dataclass(frozen=True, slots=True)
class MidiConversionResult:
    notes: list[MidiNote]
    transpose: int
    source_note_count: int
    track_name: str


class MidiConverter:
    """Convert a Standard MIDI file into a playable monophonic score."""

    def convert(self, source: Path) -> MidiConversionResult:
        if not source.is_file():
            raise FileNotFoundError(f"找不到 MIDI 文件：{source}")
        if source.suffix.lower() not in {".mid", ".midi"}:
            raise ValueError("请选择 .mid 或 .midi 文件")

        try:
            import mido
        except ImportError as exc:
            raise RuntimeError("MIDI 转换组件不完整，请重新安装软件") from exc

        try:
            midi_file = mido.MidiFile(str(source), clip=True)
        except (OSError, ValueError, EOFError) as exc:
            raise ValueError(f"无法读取 MIDI 文件：{exc}") from exc

        tempo_map = _build_tempo_map(midi_file)
        candidates = _collect_candidates(midi_file, tempo_map)
        if not candidates:
            raise ValueError("MIDI 中没有找到可演奏的非鼓点音符")

        selected = max(candidates, key=lambda item: item.score)
        melody = _monophonize(selected.notes)
        if not melody:
            raise ValueError("自动选择的旋律轨道没有有效音符")
        notes, transpose = adapt_midi_to_game_range(melody)
        return MidiConversionResult(
            notes=notes,
            transpose=transpose,
            source_note_count=len(selected.notes),
            track_name=selected.display_name,
        )


class TempoMap:
    def __init__(self, ticks_per_beat: int, changes: list[tuple[int, int]]) -> None:
        self.ticks_per_beat = ticks_per_beat
        self.points: list[tuple[int, float, int]] = []
        current_tick = 0
        current_seconds = 0.0
        current_tempo = 500_000
        self.points.append((0, 0.0, current_tempo))
        for tick, tempo in changes:
            if tick < current_tick:
                continue
            current_seconds += _ticks_to_seconds(
                tick - current_tick,
                current_tempo,
                ticks_per_beat,
            )
            current_tick = tick
            current_tempo = tempo
            if self.points and self.points[-1][0] == tick:
                self.points[-1] = (tick, current_seconds, tempo)
            else:
                self.points.append((tick, current_seconds, tempo))

    def seconds_at(self, tick: int) -> float:
        point = self.points[0]
        for candidate in self.points[1:]:
            if candidate[0] > tick:
                break
            point = candidate
        base_tick, base_seconds, tempo = point
        return base_seconds + _ticks_to_seconds(
            tick - base_tick,
            tempo,
            self.ticks_per_beat,
        )


def _ticks_to_seconds(ticks: int, tempo: int, ticks_per_beat: int) -> float:
    return ticks * tempo / 1_000_000.0 / ticks_per_beat


def _build_tempo_map(midi_file) -> TempoMap:  # type: ignore[no-untyped-def]
    ordered: list[tuple[int, int, int]] = []
    sequence = 0
    for track in midi_file.tracks:
        absolute_tick = 0
        for message in track:
            absolute_tick += int(message.time)
            if message.type == "set_tempo":
                ordered.append((absolute_tick, sequence, int(message.tempo)))
                sequence += 1
    ordered.sort(key=lambda item: (item[0], item[1]))
    return TempoMap(
        midi_file.ticks_per_beat,
        [(tick, tempo) for tick, _sequence, tempo in ordered],
    )


def _collect_candidates(midi_file, tempo_map: TempoMap) -> list[MidiCandidate]:  # type: ignore[no-untyped-def]
    result: list[MidiCandidate] = []
    for track_index, track in enumerate(midi_file.tracks):
        track_name = (getattr(track, "name", "") or f"轨道 {track_index + 1}").strip()
        absolute_tick = 0
        active: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        by_channel: dict[int, list[MidiSourceNote]] = defaultdict(list)
        for message in track:
            absolute_tick += int(message.time)
            if not hasattr(message, "channel"):
                continue
            channel = int(message.channel)
            if channel == 9:
                continue
            key = (channel, int(getattr(message, "note", -1)))
            if message.type == "note_on" and int(message.velocity) > 0:
                active[key].append((absolute_tick, int(message.velocity)))
            elif message.type in {"note_off", "note_on"} and active.get(key):
                start_tick, velocity = active[key].pop(0)
                if absolute_tick > start_tick:
                    by_channel[channel].append(
                        MidiSourceNote(
                            start_tick=start_tick,
                            end_tick=absolute_tick,
                            start=tempo_map.seconds_at(start_tick),
                            end=tempo_map.seconds_at(absolute_tick),
                            midi=key[1],
                            velocity=velocity,
                            channel=channel,
                        )
                    )

        for (channel, midi), starts in active.items():
            for start_tick, velocity in starts:
                end_tick = max(start_tick + 1, absolute_tick)
                by_channel[channel].append(
                    MidiSourceNote(
                        start_tick=start_tick,
                        end_tick=end_tick,
                        start=tempo_map.seconds_at(start_tick),
                        end=tempo_map.seconds_at(end_tick),
                        midi=midi,
                        velocity=velocity,
                        channel=channel,
                    )
                )

        for channel, notes in by_channel.items():
            if len(notes) < 3:
                continue
            ordered_notes = tuple(sorted(notes, key=lambda note: (note.start_tick, note.midi)))
            result.append(
                MidiCandidate(
                    track_index=track_index,
                    track_name=track_name,
                    channel=channel,
                    notes=ordered_notes,
                    score=_candidate_score(track_name, ordered_notes),
                )
            )
    return result


def _candidate_score(name: str, notes: tuple[MidiSourceNote, ...]) -> float:
    lowered = name.casefold()
    positive_names = (
        "melody", "vocal", "voice", "lead", "solo", "soprano", "right", "rh",
        "旋律", "主音", "主奏", "人声", "独奏", "右手",
    )
    negative_names = (
        "drum", "bass", "chord", "pad", "accomp", "percussion", "left", "lh",
        "鼓", "贝斯", "低音", "和弦", "伴奏", "打击", "左手",
    )
    score = 0.0
    if any(value in lowered for value in positive_names):
        score += 5.0
    if any(value in lowered for value in negative_names):
        score -= 5.0

    duration = max(note.end for note in notes) - min(note.start for note in notes)
    density = len(notes) / max(duration, 0.01)
    pitches = sorted(note.midi for note in notes)
    median_pitch = pitches[len(pitches) // 2]
    overlaps = sum(
        current.start < previous.end - 0.01
        for previous, current in zip(notes, notes[1:])
    )
    monophony = 1.0 - overlaps / max(1, len(notes) - 1)

    score += monophony * 5.0
    score += min(3.0, math.log2(len(notes) + 1) * 0.35)
    if 52 <= median_pitch <= 88:
        score += 2.0
    elif median_pitch < 45:
        score -= 2.5
    if 0.35 <= density <= 10.0:
        score += 1.0
    elif density > 16.0:
        score -= 2.0
    return score


def _monophonize(notes: tuple[MidiSourceNote, ...]) -> list[MidiNote]:
    grouped: list[list[MidiSourceNote]] = []
    for note in notes:
        if grouped and grouped[-1][0].start_tick == note.start_tick:
            grouped[-1].append(note)
        else:
            grouped.append([note])

    chosen = [
        max(group, key=lambda note: (note.midi, note.velocity, note.end_tick - note.start_tick))
        for group in grouped
    ]
    if not chosen:
        return []

    trim_offset = max(0.0, chosen[0].start - 0.05)
    result: list[MidiNote] = []
    for index, note in enumerate(chosen):
        next_start = chosen[index + 1].start if index + 1 < len(chosen) else math.inf
        end = min(note.end, next_start)
        duration = end - note.start
        if duration < 0.025:
            continue
        result.append(
            MidiNote(
                start=max(0.0, note.start - trim_offset),
                duration=duration,
                midi=note.midi,
                confidence=max(0.05, note.velocity / 127.0),
            )
        )
    return result


def adapt_midi_to_game_range(notes: list[MidiNote]) -> tuple[list[MidiNote], int]:
    if not notes:
        return [], 0
    candidates_by_class: dict[int, list[int]] = defaultdict(list)
    for pitch in NOTE_MAP:
        candidates_by_class[pitch % 12].append(pitch)

    best_cost = math.inf
    best_shift = 0
    best_path: list[int] = []
    for shift in range(-11, 13):
        states: dict[int, tuple[float, list[int]]] = {}
        first = notes[0]
        first_target = first.midi + shift
        for pitch in candidates_by_class[first_target % 12]:
            states[pitch] = (_placement_cost(pitch, first_target), [pitch])

        for previous_note, note in zip(notes, notes[1:]):
            target = note.midi + shift
            original_interval = note.midi - previous_note.midi
            next_states: dict[int, tuple[float, list[int]]] = {}
            for pitch in candidates_by_class[target % 12]:
                best_state: tuple[float, list[int]] | None = None
                for previous_pitch, (cost, path) in states.items():
                    mapped_interval = pitch - previous_pitch
                    transition_cost = abs(mapped_interval - original_interval) * 0.08
                    if abs(mapped_interval) >= 12 and abs(original_interval) < 12:
                        transition_cost += 0.7
                    if NOTE_MAP[pitch].band != NOTE_MAP[previous_pitch].band:
                        transition_cost += 0.035
                    candidate = (
                        cost + _placement_cost(pitch, target) + transition_cost,
                        path + [pitch],
                    )
                    if best_state is None or candidate[0] < best_state[0]:
                        best_state = candidate
                if best_state is not None:
                    next_states[pitch] = best_state
            states = next_states

        if not states:
            continue
        cost, path = min(states.values(), key=lambda value: value[0])
        cost += abs(shift) * 0.004
        if cost < best_cost:
            best_cost = cost
            best_shift = shift
            best_path = path

    adapted = [
        MidiNote(note.start, note.duration, pitch, note.confidence)
        for note, pitch in zip(notes, best_path)
    ]
    return adapted, best_shift


def _placement_cost(pitch: int, target: int) -> float:
    modifier_cost = {
        ToneBand.NATURAL: 0.0,
        ToneBand.LOW: 0.06,
        ToneBand.HIGH: 0.06,
        ToneBand.SEMITONE: 0.18,
    }[NOTE_MAP[pitch].band]
    return abs(pitch - target) * 0.035 + modifier_cost
