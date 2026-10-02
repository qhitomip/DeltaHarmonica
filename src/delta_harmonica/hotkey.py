"""F12 support: Windows reserves F12 in RegisterHotKey, so use a filtered hook."""
import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QObject, Signal


class KeyEvent(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class F12Hotkey(QObject):
    pressed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.handle = None
        self.callback = None
        self.generation = 0
        self.held = False
        self.user32 = None

    @property
    def active(self) -> bool:
        return bool(self.handle)

    def register(self) -> bool:
        self.close()
        if sys.platform != "win32":
            return False
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        self.user32.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD]
        self.user32.SetWindowsHookExW.restype = wintypes.HANDLE
        self.user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self.user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self.callback = callback_type(self._event)
        self.held = bool(self.user32.GetAsyncKeyState(0x7B) & 0x8000)
        self.handle = self.user32.SetWindowsHookExW(13, self.callback, kernel32.GetModuleHandleW(None), 0)
        return self.active

    def _event(self, code, message, pointer):
        if code >= 0 and self.active:
            event = KeyEvent.from_address(pointer)
            if event.vkCode == 0x7B and not event.flags & 0x10:
                if message in (0x0100, 0x0104):
                    if not self.held:
                        self.held = True
                        self.pressed.emit(self.generation)
                    return 1
                if message in (0x0101, 0x0105):
                    self.held = False
                    return 1
        return self.user32.CallNextHookEx(self.handle, code, message, pointer)

    def close(self) -> None:
        self.generation += 1
        if self.handle:
            self.user32.UnhookWindowsHookEx(self.handle)
            self.handle = None
        # Keep the callback alive until the next registration/object destruction.
        self.held = False
