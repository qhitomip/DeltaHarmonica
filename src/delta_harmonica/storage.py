from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .game_io import NOTE_MAP
from .midi import MidiNote
from .presets import PRESETS, find_preset
from .settings import HOTKEYS, MIN_SPEED, MAX_SPEED


MIDI_EXTENSIONS = {".mid", ".midi"}


def data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    parent = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    target = parent / "DeltaHarmonicaNext"
    target.mkdir(parents=True, exist_ok=True)
    return target


def converted_directory() -> Path:
    target = data_directory() / "converted"
    target.mkdir(parents=True, exist_ok=True)
    return target


@dataclass(slots=True)
class Preferences:
    delay_seconds: int = 3
    hotkey: str = "F6"
    overlay_enabled: bool = True
    theme: str = "dark"


class PreferencesStore:
    def load(self) -> Preferences:
        path = data_directory() / "preferences.json"
        if not path.exists():
            return Preferences()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload["format"] != "delta-harmonica-midi-preferences-2":
                raise ValueError("不支持的设置格式")
            delay = max(0, min(30, int(payload.get("delay_seconds", 3))))
            return Preferences(
                delay_seconds=delay,
                hotkey=_normalize_hotkey(payload.get("hotkey")),
                overlay_enabled=payload.get("overlay_enabled", True) is True,
                theme="light" if payload.get("theme") == "light" else "dark",
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return Preferences()

    def save(self, preferences: Preferences) -> None:
        path = data_directory() / "preferences.json"
        _write_json(path, {"format": "delta-harmonica-midi-preferences-2", **asdict(preferences)})


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
    speed_percent: int = 100

    @property
    def is_builtin(self) -> bool:
        return find_preset(self.id) is not None

    @property
    def exists(self) -> bool:
        return self.is_builtin or Path(self.source_path).is_file()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MidiSong":
        song = cls(**payload)
        song.speed_percent = max(MIN_SPEED, min(MAX_SPEED, int(song.speed_percent)))
        preset = find_preset(song.id)
        if preset:
            song.title = preset.title
        return song

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MidiLibrary:
    def __init__(self) -> None:
        self._songs = self._load()

    @property
    def songs(self) -> list[MidiSong]:
        return list(self._songs)

    @staticmethod
    def _defaults() -> list[MidiSong]:
        return [MidiSong(id=preset.id, title=preset.title, source_path="", file_size=0,
                        imported_at="", status="任务片段", track_name="固定旋律")
                for preset in PRESETS]

    def import_files(self, paths: list[str]) -> tuple[list[MidiSong], list[str]]:
        imported: list[MidiSong] = []
        errors: list[str] = []
        songs = list(self._songs)
        known = {Path(song.source_path).resolve() for song in songs if not song.is_builtin}
        for raw_path in paths:
            candidate = Path(raw_path).expanduser()
            try:
                source = candidate.resolve(strict=True)
            except OSError:
                errors.append(f"找不到文件：{candidate.name or raw_path}")
                continue
            if not source.is_file() or source.suffix.lower() not in MIDI_EXTENSIONS:
                errors.append(f"仅支持 MIDI 曲谱（.mid / .midi）：{source.name}")
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
            songs.insert(0, song)
            known.add(source)
            imported.append(song)
        if imported:
            self._save(songs)
        return imported, errors

    def update(self, song: MidiSong) -> None:
        for index, existing in enumerate(self._songs):
            if existing.id == song.id:
                songs = list(self._songs)
                songs[index] = song
                self._save(songs)
                return
        raise KeyError(song.id)

    def remove(self, song_id: str) -> None:
        self._save([song for song in self._songs if song.id != song_id])

    def _load(self) -> list[MidiSong]:
        path = data_directory() / "library.json"
        if not path.exists():
            return self._defaults()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload["format"] != "delta-harmonica-midi-library-2":
                raise ValueError("不支持的曲库格式")
            songs = [MidiSong.from_dict(item) for item in payload.get("songs", [])]
            return [song for song in songs if song.is_builtin or Path(song.source_path).suffix.lower() in MIDI_EXTENSIONS]
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            return self._defaults()

    def _save(self, songs: list[MidiSong]) -> None:
        path = data_directory() / "library.json"
        _write_json(path, {"format": "delta-harmonica-midi-library-2", "songs": [song.to_dict() for song in songs]})
        self._songs = songs


def load_performance(path: str | Path) -> list[MidiNote]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("format") != "delta-harmonica-score-1":
        raise ValueError("不支持的转换文件")
    records = payload.get("notes")
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ValueError("转换文件中的音符列表无效")
    return validate_notes([MidiNote.from_dict(item) for item in records])


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
            "format": "delta-harmonica-score-1",
            "source": source,
            "transpose": transpose,
            "notes": [note.to_dict() for note in validate_notes(notes)],
        },
    )


def validate_notes(notes: list[MidiNote]) -> list[MidiNote]:
    if not notes:
        raise ValueError("曲谱没有可演奏的音符")
    ordered = sorted(notes, key=lambda note: note.start)
    previous_end = 0.0
    for note in ordered:
        if (not math.isfinite(note.start) or not math.isfinite(note.duration)
                or not math.isfinite(note.end) or note.start < 0 or note.duration <= 0):
            raise ValueError("转换结果包含无效时间")
        if note.midi not in NOTE_MAP:
            raise ValueError(f"曲谱包含口琴无法演奏的音高：{note.midi}")
        if note.start < previous_end - 1e-9:
            raise ValueError("转换结果包含重叠音符")
        previous_end = note.end
    return ordered


def _normalize_hotkey(value: object) -> str:
    hotkey = str(value or "F6").upper()
    return hotkey if hotkey in HOTKEYS else "F6"


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
