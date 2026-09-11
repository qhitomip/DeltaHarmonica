from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .midi import MidiNote


MIDI_EXTENSIONS = {".mid", ".midi"}


def data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    parent = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    target = parent / "DeltaHarmonicaMidi"
    target.mkdir(parents=True, exist_ok=True)
    return target


def converted_directory() -> Path:
    target = data_directory() / "converted"
    target.mkdir(parents=True, exist_ok=True)
    return target


@dataclass(slots=True)
class Preferences:
    delay_seconds: int = 0
    hotkey: str = "F8"
    playback_mode: str = "stable"
    speed_percent: int = 95


class PreferencesStore:
    def load(self) -> Preferences:
        path = data_directory() / "preferences.json"
        if not path.exists():
            return Preferences()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            delay = max(0, min(30, int(payload.get("delay_seconds", 0))))
            mode = str(payload.get("playback_mode", "stable"))
            if mode not in {"stable", "original"}:
                mode = "stable"
            speed = max(60, min(120, int(payload.get("speed_percent", 95))))
            return Preferences(
                delay_seconds=delay,
                hotkey=_normalize_hotkey(payload.get("hotkey")),
                playback_mode=mode,
                speed_percent=speed,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return Preferences()

    def save(self, preferences: Preferences) -> None:
        path = data_directory() / "preferences.json"
        _write_json(path, asdict(preferences))


@dataclass(slots=True)
class MidiSong:
    id: str
    title: str
    source_path: str
    file_size: int
    imported_at: str
    status: str = "待转换"
    converted_path: str | None = None
    track_index: int | None = None
    channel: int | None = None
    selection_confidence: str = ""
    track_name: str = ""

    @property
    def exists(self) -> bool:
        return Path(self.source_path).is_file()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MidiSong":
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MidiLibrary:
    def __init__(self) -> None:
        self._songs = self._load()

    @property
    def songs(self) -> list[MidiSong]:
        return list(self._songs)

    def import_files(self, paths: list[str]) -> tuple[list[MidiSong], list[str]]:
        imported: list[MidiSong] = []
        errors: list[str] = []
        known = {Path(song.source_path).resolve() for song in self._songs}
        for raw_path in paths:
            candidate = Path(raw_path).expanduser()
            try:
                source = candidate.resolve(strict=True)
            except OSError:
                errors.append(f"找不到文件：{candidate.name or raw_path}")
                continue
            if not source.is_file() or source.suffix.lower() not in MIDI_EXTENSIONS:
                errors.append(f"不支持的文件：{source.name}")
                continue
            if source in known:
                errors.append(f"已经导入：{source.name}")
                continue
            song = MidiSong(
                id=uuid.uuid4().hex,
                title=source.stem,
                source_path=str(source),
                file_size=source.stat().st_size,
                imported_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            )
            self._songs.insert(0, song)
            known.add(source)
            imported.append(song)
        if imported:
            self._save()
        return imported, errors

    def update(self, song: MidiSong) -> None:
        for index, existing in enumerate(self._songs):
            if existing.id == song.id:
                self._songs[index] = song
                self._save()
                return
        raise KeyError(song.id)

    def remove(self, song_id: str) -> None:
        self._songs = [song for song in self._songs if song.id != song_id]
        self._save()

    def _load(self) -> list[MidiSong]:
        path = data_directory() / "library.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            songs = [MidiSong.from_dict(item) for item in payload.get("songs", [])]
            return [song for song in songs if Path(song.source_path).suffix.lower() in MIDI_EXTENSIONS]
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return []

    def _save(self) -> None:
        path = data_directory() / "library.json"
        _write_json(path, {"songs": [song.to_dict() for song in self._songs]})


def load_performance(path: str | Path) -> list[MidiNote]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("format") != "delta-harmonica-midi-1":
        raise ValueError("不支持的转换文件")
    return validate_notes([MidiNote.from_dict(item) for item in payload.get("notes", [])])


def save_performance(
    path: str | Path,
    notes: list[MidiNote],
    *,
    source: str | None = None,
    transpose: int = 0,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(
        target,
        {
            "format": "delta-harmonica-midi-1",
            "source": source,
            "transpose": transpose,
            "notes": [note.to_dict() for note in validate_notes(notes)],
        },
    )


def validate_notes(notes: list[MidiNote]) -> list[MidiNote]:
    ordered = sorted(notes, key=lambda note: note.start)
    previous_end = 0.0
    for note in ordered:
        if note.start < 0 or note.duration <= 0:
            raise ValueError("转换结果包含无效时间")
        if note.start < previous_end - 0.001:
            raise ValueError("转换结果包含重叠音符")
        previous_end = note.end
    return ordered


def _normalize_hotkey(value: object) -> str:
    hotkey = str(value or "F8").upper()
    return hotkey if hotkey in {f"F{number}" for number in range(6, 13)} else "F8"


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
