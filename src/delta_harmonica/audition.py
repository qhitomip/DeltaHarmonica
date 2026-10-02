"""Local MIDI synth audition. This module never imports or sends game input."""
from __future__ import annotations

import ctypes
import math
import sys
import time

from PySide6.QtCore import QObject, QTimer, Qt, Signal

from .settings import MIN_SPEED, MAX_SPEED
from .midi import MidiNote, MidiCandidate


class WindowsMidiOutput:
    def __init__(self):
        if sys.platform != 'win32':
            raise OSError('本地试听需要 Windows MIDI 合成器')
        self.dll = ctypes.WinDLL('winmm.dll')
        self.handle = ctypes.c_void_p()
        self.dll.midiOutOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint,
                                         ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint]
        self.dll.midiOutOpen.restype = ctypes.c_uint
        self.dll.midiOutShortMsg.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.dll.midiOutShortMsg.restype = ctypes.c_uint
        for name in ('midiOutReset', 'midiOutClose'):
            function = getattr(self.dll, name)
            function.argtypes = [ctypes.c_void_p]
            function.restype = ctypes.c_uint
        result = self.dll.midiOutOpen(ctypes.byref(self.handle), 0xFFFFFFFF, 0, 0, 0)
        if result:
            raise OSError(f'无法打开 Windows MIDI 合成器（{result}），请检查音频设备')
        try:
            self.send(0xC0)  # General MIDI piano; not a captured game harmonica.
        except Exception:
            self.close()
            raise

    def send(self, message: int):
        result = self.dll.midiOutShortMsg(self.handle, message)
        if result:
            raise OSError(f'MIDI 试听输出失败（{result}）')

    def close(self):
        if not self.handle.value:
            return
        reset_error = self.dll.midiOutReset(self.handle)
        close_error = self.dll.midiOutClose(self.handle)
        if not close_error:
            self.handle = ctypes.c_void_p()
        if reset_error or close_error:
            raise OSError(f'试听设备清理失败（{reset_error}/{close_error}）')


def candidate_preview_notes(candidate: MidiCandidate) -> list[MidiNote]:
    offset = min((note.start for note in candidate.notes), default=0)
    return [MidiNote(note.start - offset, note.end - note.start, note.midi)
            for note in candidate.notes if note.end > note.start]


class MidiAudition(QObject):
    state_changed = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, parent=None, *, output_factory=WindowsMidiOutput, clock=time.perf_counter):
        super().__init__(parent)
        self.output_factory = output_factory
        self.clock = clock
        self.output = None
        self.events = []
        self.active_ids = {}
        self.pitch_counts = {}
        self.position = 0
        self.started_at = 0.0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(5)
        self.timer.timeout.connect(self._tick)

    @property
    def is_running(self):
        return self.output is not None and self.timer.isActive()

    def start(self, notes: list[MidiNote], speed_percent=100):
        self.stop()
        if self.output is not None:
            return  # A device that failed to close must not be silently replaced.
        try:
            if not notes:
                raise ValueError('没有可试听的音符')
            factor = max(MIN_SPEED, min(MAX_SPEED, int(speed_percent))) / 100
            offset = min(note.start for note in notes)
            self.events = []
            for index, note in enumerate(notes):
                if (not math.isfinite(note.start) or not math.isfinite(note.duration)
                        or note.duration <= 0 or not 0 <= note.midi <= 127):
                    raise ValueError('试听音符无效')
                start, end = (note.start - offset) / factor, (note.end - offset) / factor
                self.events.extend([(start, 1, index, note.midi, end), (end, 0, index, note.midi, end)])
            self.events.sort()  # Note-off before note-on at the same timestamp.
            self.output = self.output_factory()
            self.active_ids.clear()
            self.pitch_counts.clear()
            self.position = 0
            self.started_at = self.clock()
            self.timer.start()
            self.state_changed.emit('正在试听 · 钢琴合成音色')
            self._tick()
        except Exception as exc:
            self.stop()
            self.failed.emit(str(exc))

    def _tick(self):
        if not self.is_running:
            return
        try:
            elapsed = self.clock() - self.started_at
            while self.position < len(self.events) and self.events[self.position][0] <= elapsed:
                _, on, index, pitch, end = self.events[self.position]
                self.position += 1
                if on:
                    if end <= elapsed:
                        continue
                    count = self.pitch_counts.get(pitch, 0)
                    if count == 0:
                        self.output.send(0x90 | pitch << 8 | 85 << 16)
                    self.pitch_counts[pitch] = count + 1
                    self.active_ids[index] = pitch
                elif index in self.active_ids:
                    self.active_ids.pop(index)
                    count = self.pitch_counts[pitch] - 1
                    self.pitch_counts[pitch] = count
                    if count == 0:
                        self.output.send(0x80 | pitch << 8)
            if self.position == len(self.events):
                self.stop(completed=True)
        except Exception as exc:
            self.stop()
            self.failed.emit(str(exc))

    def stop(self, *, completed=False):
        had_output = self.output is not None
        error = None
        self.timer.stop()
        if self.output is not None:
            try:
                self.output.close()
                self.output = None
            except Exception as exc:
                error = str(exc)
        self.active_ids.clear()
        self.pitch_counts.clear()
        if had_output:
            if error is None:
                self.state_changed.emit('试听完成' if completed else '试听已停止')
            self.finished.emit()
        if error is not None:
            self.failed.emit(error)
