from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .ui import MainWindow


def main() -> int:
    midi_source = os.environ.get("DELTA_HARMONICA_MIDI_SMOKE_SOURCE")
    if midi_source:
        try:
            from .midi import MidiConverter
            from .storage import save_performance

            output = Path(os.environ.get("DELTA_HARMONICA_MIDI_SMOKE_OUTPUT", "midi-smoke-score.json"))
            result = MidiConverter().convert(Path(midi_source))
            save_performance(output, result.notes, source=midi_source, transpose=result.transpose)
            return 0
        except Exception:
            log_path = os.environ.get("DELTA_HARMONICA_MIDI_SMOKE_LOG")
            if log_path:
                Path(log_path).write_text(traceback.format_exc(), encoding="utf-8")
            return 2

    app = QApplication(sys.argv)
    app.setApplicationName("Delta Harmonica")
    app.setOrganizationName("沙拉Sarada")
    app.setOrganizationDomain("https://space.bilibili.com/501585047")
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon())
    window = MainWindow()
    window.show()
    smoke_exit_ms = "700" if "--smoke-test" in sys.argv else os.environ.get("DELTA_HARMONICA_SMOKE_EXIT_MS")
    if smoke_exit_ms:
        QTimer.singleShot(max(1, int(smoke_exit_ms)), app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
