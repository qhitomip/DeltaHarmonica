from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from .game_io import GameInput, GameKey, NOTE_KEYS, NOTE_MAP, ToneBand
from .settings import MIN_SPEED, MAX_SPEED
from .midi import MidiNote


@dataclass(frozen=True, slots=True)
class PerformanceTiming:
    speed_percent: int = 100
    minimum_press_seconds: float = 0.08
    minimum_gap_seconds: float = 0.025
    modifier_lead_seconds: float = 0.025

    @classmethod
    def for_speed(cls, speed_percent: int) -> "PerformanceTiming":
        speed = max(MIN_SPEED, min(MAX_SPEED, int(speed_percent)))
        return cls(speed_percent=speed)


class PerformanceState(str, Enum):
    PREPARING = "准备演奏"
    COUNTDOWN = "倒计时"
    PLAYING = "正在演奏"
    STOPPING = "正在停止并释放按键"
    STOPPED = "已停止"
    COMPLETED = "演奏完成"
    FAILED = "演奏失败"


@dataclass(slots=True)
class PerformanceDiagnostics:
    speed_percent: int
    note_count: int
    short_notes: int = 0
    tight_gaps: int = 0
    short_modifier_leads: int = 0
    played_notes: int = 0
    skipped_expired_notes: int = 0
    late_notes: int = 0
    cleanup_failed: bool = False

    def summary(self) -> str:
        text = f"本次速度 {self.speed_percent}%"
        if self.short_notes or self.tight_gaps or self.short_modifier_leads:
            text += (
                f" · 密集输入风险：短音 {self.short_notes}，间隔不足 {self.tight_gaps}，"
                f"音区准备不足 {self.short_modifier_leads}；保持所选速度，可能吞音"
            )
        text += f" · 已发送 {self.played_notes}/{self.note_count} 音"
        if self.skipped_expired_notes or self.late_notes:
            text += f" · 过期跳过 {self.skipped_expired_notes}，迟到 {self.late_notes}"
        return text


def resolve_keys(notes: list[MidiNote], keys: list[GameKey] | None = None) -> list[GameKey]:
    if keys is None:
        return [NOTE_MAP[note.midi] for note in notes]
    if len(keys) != len(notes) or any(key.virtual_key not in NOTE_KEYS or not isinstance(key.band, ToneBand) for key in keys):
        raise ValueError("任务按键数据与音符不匹配")
    return list(keys)


def build_performance_schedule(notes: list[MidiNote], timing: PerformanceTiming,
                               keys: list[GameKey] | None = None) -> list[MidiNote]:
    """Keep every onset and the song end at the selected speed; only trim tails."""
    if timing.speed_percent == 100 and timing.minimum_gap_seconds == 0 and timing.modifier_lead_seconds == 0:
        return list(notes)
    event_keys = resolve_keys(notes, keys)
    factor = timing.speed_percent / 100.0
    scheduled: list[MidiNote] = []
    for index, note in enumerate(notes):
        start, end = note.start / factor, note.end / factor
        if index + 1 < len(notes):
            following = notes[index + 1]
            next_start = following.start / factor
            changes_band = event_keys[index].band != event_keys[index + 1].band
            reserve = max(
                timing.minimum_gap_seconds,
                timing.modifier_lead_seconds if changes_band else 0.0,
            )
            available = next_start - start
            # Dense passages share their available slot between sound and release.
            # Never push the next onset or lengthen the song to meet a minimum.
            tail_limit = next_start - min(reserve, available / 2.0)
            end = min(end, tail_limit)
        scheduled.append(MidiNote(start, end - start, note.midi, note.confidence))
    return scheduled


def diagnose_schedule(notes: list[MidiNote], timing: PerformanceTiming,
                      keys: list[GameKey] | None = None) -> PerformanceDiagnostics:
    event_keys = resolve_keys(notes, keys)
    result = PerformanceDiagnostics(timing.speed_percent, len(notes))
    # Risk thresholds do not change when a custom timing value is zero.
    limits = PerformanceTiming(speed_percent=timing.speed_percent)
    for index, note in enumerate(notes):
        result.short_notes += int(note.duration < limits.minimum_press_seconds - 1e-9)
        if index:
            previous = notes[index - 1]
            gap = note.start - previous.end
            result.tight_gaps += int(gap < limits.minimum_gap_seconds - 1e-9)
            if (event_keys[index].band != ToneBand.NATURAL
                    and event_keys[index].band != event_keys[index - 1].band):
                result.short_modifier_leads += int(gap < limits.modifier_lead_seconds - 1e-9)
    if notes and event_keys[0].band != ToneBand.NATURAL:
        result.short_modifier_leads += int(timing.modifier_lead_seconds < limits.modifier_lead_seconds)
    return result


class PlaybackEngine:
    """Single input owner. Clock, waits and input are injectable for non-game tests."""

    def __init__(
        self, game_input: GameInput, cancel: threading.Event, gate: threading.Lock,
        *, clock: Callable[[], float] = time.perf_counter,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        self.input = game_input
        self.cancel = cancel
        self.gate = gate
        self.clock = clock
        self.wait = wait or cancel.wait

    def wait_until(self, deadline: float) -> bool:
        while not self.cancel.is_set():
            remaining = deadline - self.clock()
            if remaining <= 0:
                return True
            self.wait(min(remaining, 0.01))
        return False

    def command(self, action: Callable[[], None]) -> bool:
        # stop() sets cancellation under this same gate: no new down can follow it.
        with self.gate:
            if self.cancel.is_set():
                return False
            action()
            return True

    def play(
        self, notes: list[MidiNote], timing: PerformanceTiming,
        diagnostics: PerformanceDiagnostics, progress: Callable[[float], None],
        keys: list[GameKey] | None = None,
        *, timeline_started: Callable[[float, float], None] | None = None,
    ) -> None:
        event_keys = resolve_keys(notes, keys)
        epoch = self.clock() + timing.modifier_lead_seconds
        total = notes[-1].end if notes else 0.0
        if timeline_started is not None:
            timeline_started(epoch, total)
        for index, note in enumerate(notes):
            if self.cancel.is_set():
                return
            key = event_keys[index]
            if key.band != self.input.active_band:
                # Negative relative prepare time is intentional for the first note.
                if not self.wait_until(epoch + note.start - timing.modifier_lead_seconds):
                    return
                if self.clock() >= epoch + note.end:
                    diagnostics.skipped_expired_notes += 1
                    progress(min(1.0, note.end / total))
                    continue
                if not self.command(lambda: self.input.prepare_band(key.band)):
                    return
            if not self.wait_until(epoch + note.start):
                return
            with self.gate:
                if self.cancel.is_set():
                    return
                now = self.clock()
                if now >= epoch + note.end:
                    diagnostics.skipped_expired_notes += 1
                    progress(min(1.0, note.end / total))
                    continue
                diagnostics.late_notes += int(now - (epoch + note.start) > 0.005)
                self.input.press_note(key)
                diagnostics.played_notes += 1
            if not self.wait_until(epoch + note.end):
                return
            self.input.release_note()
            following = notes[index + 1] if index + 1 < len(notes) else None
            keep_band = bool(following and event_keys[index + 1].band == key.band
                             and following.start - note.end <= 0.08)
            if not keep_band:
                self.input.release_band()
            if total > 0:
                progress(min(1.0, note.end / total))


class MidiPerformer(QObject):
    state_changed = Signal(str)
    progress_changed = Signal(float)
    timeline_started = Signal(float, float)
    diagnostics_changed = Signal(str)
    failed = Signal(str)
    finished = Signal()
    _worker_finished = Signal()

    def __init__(self, *, input_factory: Callable[[], GameInput] = GameInput) -> None:
        super().__init__()
        self.hotkey_label = "F6"
        self._cancel = threading.Event()
        self._gate = threading.Lock()
        self._worker: threading.Thread | None = None
        self._input_factory = input_factory
        self.state = PerformanceState.STOPPED
        self.diagnostics: PerformanceDiagnostics | None = None
        self._worker_finished.connect(self._on_worker_finished)

    @property
    def is_running(self) -> bool:
        # Remain busy until the GUI consumes the completion signal. This prevents
        # old queued progress/finish signals from modifying a newly started session.
        return self._worker is not None

    def start(self, notes: list[MidiNote], delay_seconds: int,
              timing: PerformanceTiming | None = None, *, keys: list[GameKey] | None = None) -> None:
        if self.is_running:
            return
        try:
            if not notes:
                raise ValueError("曲谱没有可演奏的音符")
            previous_end = 0.0
            for note in notes:
                if (not math.isfinite(note.start) or not math.isfinite(note.duration)
                        or note.duration <= 0 or note.start < previous_end - 1e-9):
                    raise ValueError("曲谱包含无效时间或重叠音符")
                if note.midi not in NOTE_MAP:
                    raise ValueError(f"曲谱包含口琴无法演奏的音高：{note.midi}")
                previous_end = note.end
            keys = resolve_keys(notes, keys)
        except ValueError as exc:
            self.state = PerformanceState.FAILED
            self.state_changed.emit(self.state.value)
            self.failed.emit(str(exc))
            return
        timing = timing or PerformanceTiming()
        scheduled = build_performance_schedule(notes, timing, keys)
        self.diagnostics = diagnose_schedule(scheduled, timing, keys)
        self.diagnostics_changed.emit(self.diagnostics.summary())
        self._cancel.clear()
        self.state = PerformanceState.PREPARING
        self.state_changed.emit(self.state.value)
        self._worker = threading.Thread(target=self._perform,
                                        args=(scheduled, max(0, delay_seconds), timing, keys),
                                        daemon=False, name="midi-harmonica-performer")
        try:
            self._worker.start()
        except Exception as exc:
            self._worker = None
            self.state = PerformanceState.FAILED
            self.state_changed.emit(self.state.value)
            self.failed.emit(f"无法启动演奏线程：{exc}")

    def stop(self) -> None:
        with self._gate:
            if not self.is_running or self.state in {
                PerformanceState.STOPPED, PerformanceState.COMPLETED, PerformanceState.FAILED,
            }:
                return
            self._cancel.set()
            self.state = PerformanceState.STOPPING
            self.state_changed.emit(self.state.value)

    def shutdown(self) -> None:
        self.stop()

    def _announce(self, state: PerformanceState, message: str | None = None) -> bool:
        with self._gate:
            if self._cancel.is_set():
                return False
            self.state = state
            self.state_changed.emit(message or state.value)
            return True

    def _perform(self, notes: list[MidiNote], delay: int, timing: PerformanceTiming, keys: list[GameKey]) -> None:
        game_input = None
        error = None
        try:
            game_input = self._input_factory()
            for remaining in range(delay, 0, -1):
                if not self._announce(PerformanceState.COUNTDOWN, f"{remaining} 秒后开始"):
                    return
                if self._cancel.wait(1.0):
                    return
            if not self._announce(PerformanceState.PLAYING):
                return
            engine = PlaybackEngine(game_input, self._cancel, self._gate)
            engine.play(notes, timing, self.diagnostics, self.progress_changed.emit, keys,
                        timeline_started=self.timeline_started.emit)
        except Exception as exc:
            error = str(exc)
        finally:
            if game_input is not None:
                # Cleanup stays on the input owner thread, including cancellation.
                for attempt in range(2):
                    try:
                        game_input.release_all()
                        break
                    except Exception as exc:
                        if attempt == 1:
                            self.diagnostics.cleanup_failed = True
                            error = f"{error + '；' if error else ''}释放按键失败：{exc}。请手动按下并松开音键和鼠标键。"
            with self._gate:
                self.state = (PerformanceState.FAILED if error else
                              PerformanceState.STOPPED if self._cancel.is_set() else
                              PerformanceState.COMPLETED)
                label = self.state.value
                if self.state == PerformanceState.STOPPED:
                    label += f" · 按 {self.hotkey_label} 可从头开始"
                self.state_changed.emit(label)
            self.diagnostics_changed.emit(self.diagnostics.summary())
            if error:
                self.failed.emit(error)
            self._worker_finished.emit()

    @Slot()
    def _on_worker_finished(self) -> None:
        if self._worker is not None:
            self._worker.join()
            self._worker = None
        self.finished.emit()
