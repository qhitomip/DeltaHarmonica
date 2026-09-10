from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, Signal

from .game_io import GameInput, NOTE_MAP
from .midi import MidiNote


class MidiPerformer(QObject):
    state_changed = Signal(str)
    progress_changed = Signal(float)
    failed = Signal(str)
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.hotkey_label = "F8"
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._game_input: GameInput | None = None

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def start(self, notes: list[MidiNote], delay_seconds: int) -> None:
        if self.is_running:
            return
        unsupported = sorted({note.midi for note in notes if note.midi not in NOTE_MAP})
        if unsupported:
            self.failed.emit(f"曲谱包含口琴无法演奏的音高：{unsupported}")
            return
        self._cancel.clear()
        self._worker = threading.Thread(
            target=self._perform,
            args=(notes, delay_seconds),
            daemon=True,
            name="midi-harmonica-performer",
        )
        self._worker.start()

    def stop(self) -> None:
        self._cancel.set()
        if self._game_input is not None:
            self._game_input.release_all()
        self.state_changed.emit(f"已停止 · 按 {self.hotkey_label} 可重新开始")

    def shutdown(self) -> None:
        self._cancel.set()
        if self._game_input is not None:
            self._game_input.release_all()

    def _perform(self, notes: list[MidiNote], delay_seconds: int) -> None:
        try:
            self._game_input = GameInput()
            for remaining in range(delay_seconds, 0, -1):
                self.state_changed.emit(f"{remaining} 秒后开始")
                if self._cancel.wait(1.0):
                    return

            self.state_changed.emit("正在演奏")
            started_at = time.perf_counter()
            total = max((note.end for note in notes), default=0.0)
            for index, note in enumerate(notes):
                if not self._wait_until(started_at + note.start):
                    return
                current_key = NOTE_MAP[note.midi]
                self._game_input.press(current_key)
                if not self._wait_until(started_at + note.end):
                    return
                self._game_input.release_note()

                following = notes[index + 1] if index + 1 < len(notes) else None
                keep_band = bool(
                    following
                    and NOTE_MAP[following.midi].band == current_key.band
                    and following.start - note.end <= 0.08
                )
                if not keep_band:
                    self._game_input.release_band()
                if total > 0:
                    self.progress_changed.emit(min(1.0, note.end / total))
            self.state_changed.emit("演奏完成")
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if self._game_input is not None:
                self._game_input.release_all()
            self._game_input = None
            self._worker = None
            self.finished.emit()

    def _wait_until(self, deadline: float) -> bool:
        while not self._cancel.is_set():
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return True
            self._cancel.wait(min(remaining, 0.01))
        return False
