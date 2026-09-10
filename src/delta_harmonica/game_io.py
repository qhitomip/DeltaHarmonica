from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum


class ToneBand(str, Enum):
    LOW = "low"
    NATURAL = "natural"
    SEMITONE = "semitone"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class GameKey:
    band: ToneBand
    virtual_key: int
    label: str


NOTE_KEYS = (0x5A, 0x58, 0x43, 0x56, 0x42, 0x4E, 0x4D, 0xBC)  # Z X C V B N M ,


def _make_note_map() -> dict[int, GameKey]:
    result: dict[int, GameKey] = {}
    bands = (
        (ToneBand.LOW, (48, 50, 52, 53, 55, 57, 59, 60), "低音"),
        (ToneBand.NATURAL, (60, 62, 64, 65, 67, 69, 71, 72), ""),
        (ToneBand.SEMITONE, (61, 63, 65, 66, 68, 70, 72, 73), "半音"),
        (ToneBand.HIGH, (72, 74, 76, 77, 79, 81, 83, 84), "高音"),
    )
    for band, pitches, prefix in bands:
        for index, pitch in enumerate(pitches):
            game_key = GameKey(band, NOTE_KEYS[index], f"{prefix}{index + 1}")
            if band is ToneBand.NATURAL:
                result[pitch] = game_key
            else:
                result.setdefault(pitch, game_key)
    return result


NOTE_MAP = _make_note_map()


if sys.platform == "win32":
    ULONG_PTR = wintypes.WPARAM

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = (
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        )

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        )

    class INPUT_DATA(ctypes.Union):
        _fields_ = (("keyboard", KEYBDINPUT), ("mouse", MOUSEINPUT))

    class INPUT(ctypes.Structure):
        _anonymous_ = ("data",)
        _fields_ = (("type", wintypes.DWORD), ("data", INPUT_DATA))


class GameInput:
    KEY_UP = 0x0002
    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1
    MOUSE_EVENTS = {
        ToneBand.LOW: (0x0002, 0x0004),
        ToneBand.SEMITONE: (0x0020, 0x0040),
        ToneBand.HIGH: (0x0008, 0x0010),
    }

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("按键演奏仅支持 Windows")
        self._user32 = ctypes.windll.user32
        self._active_key: int | None = None
        self._active_band = ToneBand.NATURAL

    def press(self, game_key: GameKey) -> None:
        self.release_note()
        if game_key.band is not self._active_band:
            self.release_band()
            if game_key.band is not ToneBand.NATURAL:
                down_event, _ = self.MOUSE_EVENTS[game_key.band]
                self._send_mouse(down_event)
                self._active_band = game_key.band
        self._send_key(game_key.virtual_key, key_up=False)
        self._active_key = game_key.virtual_key

    def release_note(self) -> None:
        if self._active_key is not None:
            self._send_key(self._active_key, key_up=True)
            self._active_key = None

    def release_band(self) -> None:
        if self._active_band is not ToneBand.NATURAL:
            _, up_event = self.MOUSE_EVENTS[self._active_band]
            self._send_mouse(up_event)
            self._active_band = ToneBand.NATURAL

    def release_all(self) -> None:
        self.release_note()
        self.release_band()

    def _send_key(self, virtual_key: int, *, key_up: bool) -> None:
        flags = self.KEY_UP if key_up else 0
        event = INPUT(
            type=self.INPUT_KEYBOARD,
            data=INPUT_DATA(keyboard=KEYBDINPUT(virtual_key, 0, flags, 0, 0)),
        )
        if self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
            raise ctypes.WinError()

    def _send_mouse(self, flags: int) -> None:
        event = INPUT(
            type=self.INPUT_MOUSE,
            data=INPUT_DATA(mouse=MOUSEINPUT(0, 0, 0, flags, 0, 0)),
        )
        if self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
            raise ctypes.WinError()
