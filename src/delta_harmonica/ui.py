from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path
from urllib.parse import quote_plus

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .midi import MidiConversionResult, MidiConverter
from .performer import MidiPerformer
from .storage import (
    MidiLibrary,
    PreferencesStore,
    converted_directory,
    load_performance,
    save_performance,
)


MIDI_FILTER = "MIDI 曲谱 (*.mid *.midi)"
WM_HOTKEY = 0x0312
HOTKEY_ID = 0xD317
HOTKEYS = {f"F{number}": 0x6F + number for number in range(6, 13)}


class BilibiliIcon(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(22, 19)
        self.setToolTip("Bilibili")

    def sizeHint(self) -> QSize:
        return QSize(22, 19)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        blue = QColor("#00aeec")
        painter.setPen(QPen(blue, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(8, 5, 5, 2)
        painter.drawLine(14, 5, 17, 2)
        painter.drawRoundedRect(2, 5, 18, 12, 3, 3)
        painter.drawLine(7, 10, 7, 13)
        painter.drawLine(15, 10, 15, 13)


class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        title = QLabel("拖放 MIDI 曲谱到这里")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("支持 .mid、.midi · 导入后自动转换")
        subtitle.setObjectName("muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Delta Harmonica")
        self.resize(1040, 700)
        self.setMinimumSize(860, 590)

        self.library = MidiLibrary()
        self.preferences_store = PreferencesStore()
        self.preferences = self.preferences_store.load()
        self.converter = MidiConverter()
        self.performer = MidiPerformer()
        self.performer.hotkey_label = self.preferences.hotkey
        self._hotkey_registered = False

        self._build_ui()
        self._connect_signals()
        self._refresh_library()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setContentsMargins(32, 28, 32, 28)
        page.setSpacing(18)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Delta Harmonica")
        title.setObjectName("appTitle")
        subtitle = QLabel("把 MIDI 曲谱转换成《三角洲行动》口琴演奏")
        subtitle.setObjectName("muted")
        author = QLabel(
            '创作者：<a style="color:#8fa8ff;text-decoration:none" '
            'href="https://space.bilibili.com/501585047">沙拉Sarada</a>'
        )
        author.setOpenExternalLinks(True)
        author.setObjectName("muted")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        author_row = QHBoxLayout()
        author_row.setSpacing(6)
        author_row.addWidget(BilibiliIcon())
        author_row.addWidget(author)
        author_row.addStretch()
        titles.addLayout(author_row)
        header.addLayout(titles)
        header.addStretch()
        page.addLayout(header)

        import_row = QHBoxLayout()
        self.drop_zone = DropZone()
        import_row.addWidget(self.drop_zone, 1)
        self.import_button = QPushButton("选择 MIDI 曲谱")
        self.import_button.setObjectName("primary")
        self.import_button.setMinimumSize(180, 74)
        import_row.addWidget(self.import_button)
        page.addLayout(import_row)

        search_card = QFrame()
        search_card.setObjectName("searchCard")
        search_layout = QHBoxLayout(search_card)
        search_layout.setContentsMargins(18, 13, 18, 13)
        search_label = QLabel("找 MIDI")
        search_label.setObjectName("searchTitle")
        search_layout.addWidget(search_label)
        self.midi_search = QLineEdit()
        self.midi_search.setPlaceholderText("输入歌曲名或歌手；下载后拖到上方")
        self.midi_search.setClearButtonEnabled(True)
        search_layout.addWidget(self.midi_search, 1)
        self.midishow_button = QPushButton("搜索 MIDIShow")
        self.bitmidi_button = QPushButton("搜索 BitMidi")
        search_layout.addWidget(self.midishow_button)
        search_layout.addWidget(self.bitmidi_button)
        page.addWidget(search_card)

        section_row = QHBoxLayout()
        section_title = QLabel("我的 MIDI 曲谱")
        section_title.setObjectName("sectionTitle")
        section_row.addWidget(section_title)
        section_row.addStretch()
        self.remove_button = QPushButton("从列表移除")
        self.remove_button.setEnabled(False)
        section_row.addWidget(self.remove_button)
        page.addLayout(section_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("歌曲", "文件", "大小", "状态"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        page.addWidget(self.table, 1)

        controls = QFrame()
        controls.setObjectName("controlCard")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(20, 16, 20, 16)

        hotkey_label = QLabel("启停热键")
        self.hotkey = QComboBox()
        self.hotkey.addItems(list(HOTKEYS))
        self.hotkey.setCurrentText(self.preferences.hotkey)
        self.hotkey.setMinimumWidth(86)
        countdown_label = QLabel("启动延时")
        self.countdown = QSpinBox()
        self.countdown.setRange(0, 30)
        self.countdown.setSuffix(" 秒")
        self.countdown.setValue(self.preferences.delay_seconds)
        controls_layout.addWidget(hotkey_label)
        controls_layout.addWidget(self.hotkey)
        controls_layout.addSpacing(18)
        controls_layout.addWidget(countdown_label)
        controls_layout.addWidget(self.countdown)
        controls_layout.addStretch()

        self.analyze_button = QPushButton("重新转换")
        self.analyze_button.setEnabled(False)
        controls_layout.addWidget(self.analyze_button)
        page.addWidget(controls)

        status_row = QHBoxLayout()
        self.status_label = QLabel(
            f"导入 MIDI 后自动转换；切到游戏按 {self.preferences.hotkey} 开始/停止"
        )
        self.status_label.setObjectName("muted")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        status_row.addWidget(self.status_label)
        status_row.addWidget(self.progress, 1)
        page.addLayout(status_row)

        self.setStyleSheet(STYLESHEET)

    def _connect_signals(self) -> None:
        self.import_button.clicked.connect(self._choose_files)
        self.drop_zone.files_dropped.connect(self._import_files)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.remove_button.clicked.connect(self._remove_selected)
        self.analyze_button.clicked.connect(self._convert_selected)
        self.countdown.valueChanged.connect(self._save_settings)
        self.hotkey.currentTextChanged.connect(self._hotkey_changed)
        self.midishow_button.clicked.connect(self._search_midishow)
        self.bitmidi_button.clicked.connect(self._search_bitmidi)
        self.midi_search.returnPressed.connect(self._search_midishow)
        self.performer.state_changed.connect(self.status_label.setText)
        self.performer.progress_changed.connect(lambda value: self.progress.setValue(round(value * 1000)))
        self.performer.failed.connect(self._performance_failed)
        self.performer.finished.connect(self._performance_finished)

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        if not self._hotkey_registered:
            self._register_hotkey()

    def nativeEvent(self, event_type, message):  # type: ignore[no-untyped-def]
        if sys.platform == "win32":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                if self.performer.is_running:
                    self.performer.stop()
                else:
                    self._start_selected_from_hotkey()
                return True, 0
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.performer.shutdown()
        self._unregister_hotkey()
        event.accept()

    def _register_hotkey(self) -> None:
        if sys.platform != "win32":
            return
        self._unregister_hotkey()
        vk_code = HOTKEYS[self.preferences.hotkey]
        self._hotkey_registered = bool(
            ctypes.windll.user32.RegisterHotKey(int(self.winId()), HOTKEY_ID, 0, vk_code)
        )
        if not self._hotkey_registered:
            self.status_label.setText(
                f"{self.preferences.hotkey} 被其他程序占用，请换一个启停热键"
            )

    def _unregister_hotkey(self) -> None:
        if self._hotkey_registered and sys.platform == "win32":
            ctypes.windll.user32.UnregisterHotKey(int(self.winId()), HOTKEY_ID)
        self._hotkey_registered = False

    def _hotkey_changed(self, hotkey: str) -> None:
        self.preferences.hotkey = hotkey
        self.performer.hotkey_label = hotkey
        self.preferences_store.save(self.preferences)
        if self.isVisible():
            self._register_hotkey()
            if self._hotkey_registered:
                self.status_label.setText(f"启停热键已改为 {hotkey}")

    def _search_midishow(self) -> None:
        query = self.midi_search.text().strip()
        url = "https://www.midishow.com/"
        if query:
            url = f"https://www.midishow.com/search/result?q={quote_plus(query)}"
        QDesktopServices.openUrl(QUrl(url))

    def _search_bitmidi(self) -> None:
        query = self.midi_search.text().strip()
        url = "https://bitmidi.com/"
        if query:
            url = f"https://bitmidi.com/search?q={quote_plus(query)}"
        QDesktopServices.openUrl(QUrl(url))

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 MIDI 曲谱", "", MIDI_FILTER)
        if paths:
            self._import_files(paths)

    def _import_files(self, paths: list[str]) -> None:
        imported, errors = self.library.import_files(paths)
        self._refresh_library()
        if imported:
            conversion_errors: list[str] = []
            for song in imported:
                try:
                    self._convert_song(song)
                except Exception as exc:
                    conversion_errors.append(f"{song.title}：{exc}")
            self._refresh_library()
            self._select_song(imported[-1].id)
            if not conversion_errors:
                self.status_label.setText(
                    f"已导入并转换 {len(imported)} 首 MIDI · 切到游戏按 "
                    f"{self.preferences.hotkey} 开始/停止"
                )
            else:
                errors.extend(conversion_errors)
        if errors:
            QMessageBox.information(self, "部分文件未导入", "\n".join(errors))

    def _refresh_library(self) -> None:
        songs = self.library.songs
        self.table.setRowCount(len(songs))
        for row, song in enumerate(songs):
            title = QTableWidgetItem(song.title)
            title.setData(Qt.ItemDataRole.UserRole, song.id)
            source = Path(song.source_path)
            if not song.exists:
                status = "文件已移动"
            else:
                status = song.status
            values = (
                title,
                QTableWidgetItem(source.name),
                QTableWidgetItem(format_size(song.file_size)),
                QTableWidgetItem(status),
            )
            for column, item in enumerate(values):
                self.table.setItem(row, column, item)
        self._selection_changed()

    def _selection_changed(self) -> None:
        selected = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        enabled = bool(selected)
        self.remove_button.setEnabled(enabled)
        song = self._selected_song() if enabled else None
        is_midi = bool(song and Path(song.source_path).suffix.lower() in {".mid", ".midi"})
        self.analyze_button.setEnabled(enabled and bool(song and song.exists) and is_midi)

    def _selected_song(self):  # type: ignore[no-untyped-def]
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        song_id = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        return next((song for song in self.library.songs if song.id == song_id), None)

    def _remove_selected(self) -> None:
        song = self._selected_song()
        if song is None:
            return
        self.library.remove(song.id)
        self._refresh_library()
        self.status_label.setText("已从列表移除；原 MIDI 文件未删除")

    def _convert_selected(self) -> None:
        song = self._selected_song()
        if song is None:
            return
        self.progress.setValue(0)
        try:
            result = self._convert_song(song)
        except Exception as exc:
            song.status = "转换失败"
            self.library.update(song)
            self._refresh_library()
            self.status_label.setText(f"转换失败：{exc}")
            QMessageBox.warning(self, "转换失败", str(exc))
            return
        self._refresh_library()
        self._select_song(song.id)
        shift = f"+{result.transpose}" if result.transpose >= 0 else str(result.transpose)
        self.status_label.setText(
            f"转换完成：{len(result.notes)} 个音符 · {result.track_name} · 移调 {shift} 半音"
        )
        self.progress.setValue(1000)

    def _convert_song(self, song) -> MidiConversionResult:  # type: ignore[no-untyped-def]
        result = self.converter.convert(Path(song.source_path))
        target = converted_directory() / f"{song.id}.json"
        save_performance(target, result.notes, source=song.source_path, transpose=result.transpose)
        song.converted_path = str(target)
        shift = f"+{result.transpose}" if result.transpose >= 0 else str(result.transpose)
        song.status = f"可演奏 · {len(result.notes)} 音符 · {result.track_name} · 移调 {shift}"
        self.library.update(song)
        return result

    def _select_song(self, song_id: str) -> None:
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == song_id:
                self.table.selectRow(row)
                return

    def _start_selected_from_hotkey(self) -> None:
        song = self._selected_song()
        if song is None:
            self.status_label.setText("请先在列表中选择一首歌曲")
            return
        if Path(song.source_path).suffix.lower() not in {".mid", ".midi"}:
            self.status_label.setText("当前版本仅支持 MIDI 曲谱，请重新导入 .mid 或 .midi 文件")
            return
        if not song.converted_path or not Path(song.converted_path).is_file():
            self.status_label.setText("所选 MIDI 还没有完成转换")
            return
        self._start_performance(load_performance(song.converted_path))

    def _start_performance(self, notes) -> None:  # type: ignore[no-untyped-def]
        if self.performer.is_running:
            return
        self.progress.setValue(0)
        self.performer.start(notes, self.preferences.delay_seconds)

    def _performance_failed(self, message: str) -> None:
        self.status_label.setText(message)
        QMessageBox.warning(self, "演奏失败", message)

    def _performance_finished(self) -> None:
        self._selection_changed()

    def _save_settings(self) -> None:
        self.preferences.delay_seconds = self.countdown.value()
        self.preferences_store.save(self.preferences)


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


STYLESHEET = """
QWidget {
    background: #0b1020;
    color: #edf2ff;
    font-family: "Microsoft YaHei UI";
    font-size: 14px;
}
QLabel#appTitle { font-size: 28px; font-weight: 700; }
QLabel#sectionTitle { font-size: 18px; font-weight: 650; }
QLabel#dropTitle { font-size: 18px; font-weight: 650; }
QLabel#muted { color: #8f9bb3; }
QLabel#searchTitle { color: #dce6ff; font-weight: 650; }
QFrame#dropZone {
    background: #10182c;
    border: 1px dashed #52658f;
    border-radius: 14px;
}
QFrame#controlCard {
    background: #10182c;
    border: 1px solid #202c49;
    border-radius: 12px;
}
QFrame#searchCard {
    background: #10182c;
    border: 1px solid #263657;
    border-radius: 10px;
}
QPushButton {
    background: #1b2541;
    border: 1px solid #34446e;
    border-radius: 8px;
    padding: 9px 15px;
}
QPushButton:hover { background: #263354; }
QPushButton:disabled { color: #59637a; background: #12192a; border-color: #222b40; }
QPushButton#primary { background: #516dff; border-color: #6f85ff; color: white; font-weight: 650; }
QPushButton#primary:hover { background: #627cff; }
QTableWidget {
    background: #0f1628;
    alternate-background-color: #111b30;
    border: 1px solid #202c49;
    border-radius: 10px;
    gridline-color: #1d2944;
    selection-background-color: #263a72;
}
QHeaderView::section {
    background: #151f36;
    color: #aebbd6;
    border: none;
    border-bottom: 1px solid #2a3654;
    padding: 10px;
}
QTableWidget::item { padding: 9px; }
QLineEdit, QComboBox, QSpinBox {
    background: #20325a;
    color: #ffffff;
    border: 1px solid #6682df;
    border-radius: 7px;
    padding: 8px 10px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid #8198ff; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #172441; selection-background-color: #516dff; }
QSpinBox::up-button, QSpinBox::down-button {
    background: #3b5393;
    border-left: 1px solid #6682df;
    width: 22px;
}
QSpinBox::up-button { border-top-right-radius: 6px; }
QSpinBox::down-button { border-bottom-right-radius: 6px; }
QProgressBar { background: #131c31; border: none; border-radius: 3px; max-height: 6px; }
QProgressBar::chunk { background: #5b75ff; border-radius: 3px; }
"""
