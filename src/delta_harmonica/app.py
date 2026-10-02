from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    from . import __version__
    from .single_instance import SingleInstance
    from .storage import data_directory
    from .ui import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationVersion(__version__)
    app.setApplicationName("Delta Harmonica")
    app.setOrganizationName("沙拉Sarada")
    app.setOrganizationDomain("https://space.bilibili.com/501585047")
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("assets") / "app.ico")))
    try:
        instance = SingleInstance(data_directory(), app)
        if not instance.acquire():
            return 0
    except OSError as exc:
        QMessageBox.critical(None, "无法启动", str(exc))
        return 1

    window = MainWindow()

    def activate():
        if window.isMinimized():
            window.showNormal()
        window.show()
        window.raise_()
        window.activateWindow()

    instance.activated.connect(activate)
    app.aboutToQuit.connect(instance.close)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
