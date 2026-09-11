from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from .game_io import GameInput, NOTE_MAP
from .midi import MidiNote


@dataclass(frozen=True, slots=True)
class PerformanceTiming:
    speed_percent: int = 95
    minimum_press_seconds: float = 0.08
    minimum_gap_seconds: float = 0.025
    modifier_lead_seconds: float = 0.025

    @classmethod
    def for_mode(cls, mode: str, speed_percent: int) -> "PerformanceTiming":
        speed = max(60, min(120, int(speed_percent)))
        if mode == "original":
            return cls(
                speed_percent=speed,
                minimum_press_seconds=0.0,
                minimum_gap_seconds=0.0,
                modifier_lead_seconds=0.0,
            )
        return cls(speed_percent=speed)


def build_performance_schedule(
    notes: list[MidiNote],
    timing: PerformanceTiming,
) -> list[MidiNote]:
    """Fit MIDI timing to minimum input durations the game can reliably sample."""
    if (
        timing.speed_percent == 100
        and timing.minimum_press_seconds == 0
        and timing.minimum_gap_seconds == 0
    ):
        return list(notes)
    speed_factor = timing.speed_percent / 100.0
    scheduled: list[MidiNote] = []
    previous_end = -timing.minimum_gap_seconds
    for index, note in enumerate(notes):
        desired_start = note.start / speed_factor
        desired_end = note.end / speed_factor
        start = max(desired_start, previous_end + timing.minimum_gap_seconds)
        minimum_end = start + timing.minimum_press_seconds
        following = notes[index + 1] if index + 1 < len(notes) else None
        if following is not None:
            next_start = following.start / speed_factor
            latest_end = next_start - timing.minimum_gap_seconds
            if latest_end >= minimum_end:
                end = max(minimum_end, min(desired_end, latest_end))
            else:
                end = max(desired_end, minimum_end)
        else:
            end = max(desired_end, minimum_end)
        duration = max(timing.minimum_press_seconds, end - start)
        scheduled.append(MidiNote(start, duration, note.midi, note.confidence))
        previous_end = end
    return scheduled


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

    def start(
        self,
        notes: list[MidiNote],
        delay_seconds: int,
        timing: PerformanceTiming | None = None,
    ) -> None:
        if self.is_running:
            return
        unsupported = sorted({note.midi for note in notes if note.midi not in NOTE_MAP})
        if unsupported:
            self.failed.emit(f"曲谱包含口琴无法演奏的音高：{unsupported}")
            return
        self._cancel.clear()
        self._worker = threading.Thread(
            target=self._perform,
            args=(notes, delay_seconds, timing or PerformanceTiming()),
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

    def _perform(
        self,
        notes: list[MidiNote],
        delay_seconds: int,
        timing: PerformanceTiming,
    ) -> None:
        try:
            self._game_input = GameInput()
            for remaining in range(delay_seconds, 0, -1):
                self.state_changed.emit(f"{remaining} 秒后开始")
                if self._cancel.wait(1.0):
                    return

            self.state_changed.emit("正在演奏")
            scheduled = build_performance_schedule(notes, timing)
            started_at = time.perf_counter() + timing.modifier_lead_seconds
            total = max((note.end for note in scheduled), default=0.0)
            for index, note in enumerate(scheduled):
                current_key = NOTE_MAP[note.midi]
                if current_key.band is not self._game_input.active_band:
                    prepare_at = max(0.0, note.start - timing.modifier_lead_seconds)
                    if not self._wait_until(started_at + prepare_at):
                        return
                    self._game_input.prepare_band(current_key.band)
                if not self._wait_until(started_at + note.start):
                    return
                self._game_input.press_note(current_key)
                if not self._wait_until(started_at + note.end):
                    return
                self._game_input.release_note()

                following = scheduled[index + 1] if index + 1 < len(scheduled) else None
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
