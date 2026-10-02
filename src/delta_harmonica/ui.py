from __future__ import annotations

import ctypes
from dataclasses import replace
import sys
from ctypes import wintypes
from pathlib import Path
from urllib.parse import quote_plus

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QLayout,
    QScrollArea,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .themes import ThemeButton, stylesheet
from .hotkey import F12Hotkey
from .settings import HOTKEYS
from .speed_control import SpeedControl
from .overlay import PlaybackOverlay
from .audition import MidiAudition, candidate_preview_notes
from .presets import find_preset
from .midi import MidiAnalysis, MidiCandidate, MidiConversionResult, MidiConverter
from .performer import MidiPerformer, PerformanceTiming, build_performance_schedule
from .storage import (
    MIDI_EXTENSIONS,
    MidiLibrary,
    MidiSong,
    PreferencesStore,
    converted_directory,
    load_performance,
    save_performance,
)


IMPORT_FILTER = "MIDI 曲谱 (*.mid *.midi)"
WM_HOTKEY = 0x0312
HOTKEY_ID = 0x5317
MOD_NOREPEAT = 0x4000


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


class AccentSpinBox(QSpinBox):
    """Draw clear +/- marks even when QSS replaces native button glyphs."""
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
        for control, symbol in ((QStyle.SubControl.SC_SpinBoxUp, "+"),
                                (QStyle.SubControl.SC_SpinBoxDown, "−")):
            rect = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, control, self)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, symbol)


class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 12, 24, 12)
        title = QLabel("拖放 MIDI 曲谱到这里")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel(".mid / .midi")
        subtitle.setObjectName("muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in MIDI_EXTENSIONS
               for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls()
                 if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in MIDI_EXTENSIONS]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()


class TrackSelectionDialog(QDialog):
    def __init__(self, analysis: MidiAnalysis, parent: QWidget | None = None, *, speed_percent: int = 100) -> None:
        super().__init__(parent)
        self.analysis = analysis
        self.preview = MidiAudition(self)
        self.preview_speed = speed_percent
        self.setWindowTitle("选择主旋律音轨")
        self.resize(1160, 560)
        self.setMinimumSize(960, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        title = QLabel("请选择要用于口琴演奏的音轨")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        confidence = QLabel(
            f"自动推荐可信度：{analysis.confidence}　{analysis.confidence_reason}"
        )
        confidence.setObjectName("muted")
        confidence.setWordWrap(True)
        layout.addWidget(confidence)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ("推荐", "轨道 / 通道", "名称", "乐器", "音符", "时长", "音域", "单音率", "密度", "试听")
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(9, 86)

        self.table.setRowCount(len(analysis.candidates))
        for row, candidate in enumerate(analysis.candidates):
            low, high = candidate.pitch_range
            recommended = "★ 推荐" if row == analysis.recommended_index else ""
            values = (
                recommended,
                f"{candidate.track_index + 1} / {candidate.channel + 1}",
                candidate.track_name,
                candidate.instrument_name,
                str(len(candidate.notes)),
                _format_duration(candidate.duration),
                f"{_note_name(low)} – {_note_name(high)}",
                f"{candidate.monophony:.0%}",
                f"{candidate.density:.1f}/秒",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, row)
                self.table.setItem(row, column, item)
            audition = QPushButton("试听")
            audition.setStyleSheet("QPushButton { padding: 2px 6px; border-radius: 5px; }")
            audition.clicked.connect(lambda checked=False, row=row: self._preview_row(row))
            self.table.setCellWidget(row, 9, audition)
        if analysis.candidates:
            self.table.selectRow(analysis.recommended_index)
        self.table.doubleClicked.connect(self.accept)
        layout.addWidget(self.table, 1)

        hint = QLabel("单音率越高越适合口琴；钢琴和弦轨会在转换时保留同一时刻的最高音。")
        hint.setObjectName("muted")
        layout.addWidget(hint)

        preview_row = QHBoxLayout()
        self.preview_button = QPushButton("试听原音轨")
        self.preview_button.clicked.connect(self._toggle_preview)
        self.preview_status = QLabel("钢琴音色试听；从第一个音开始，不发送游戏按键")
        self.preview_status.setObjectName("muted")
        preview_row.addWidget(self.preview_button)
        preview_row.addWidget(self.preview_status, 1)
        layout.addLayout(preview_row)
        self.preview.state_changed.connect(self.preview_status.setText)
        self.preview.failed.connect(self.preview_status.setText)
        self.preview.finished.connect(lambda: self.preview_button.setText("试听原音轨"))
        self.table.itemSelectionChanged.connect(self.preview.stop)
        self.finished.connect(lambda _: self.preview.stop())

        buttons = QDialogButtonBox()
        use_button = buttons.addButton("使用所选音轨", QDialogButtonBox.ButtonRole.AcceptRole)
        use_button.setObjectName("primary")
        buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _preview_row(self, row: int) -> None:
        self.table.selectRow(row)
        self._toggle_preview()

    def _toggle_preview(self) -> None:
        if self.preview.is_running:
            self.preview.stop()
        else:
            self.preview.start(candidate_preview_notes(self.selected_candidate()), self.preview_speed)
            if self.preview.is_running:
                self.preview_button.setText("停止试听")

    def selected_candidate(self) -> MidiCandidate:
        rows = self.table.selectionModel().selectedRows()
        row = rows[0].row() if rows else self.analysis.recommended_index
        return self.analysis.candidates[row]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Delta Harmonica")
        self.resize(1240, 820)
        self.setMinimumSize(1040, 700)

        self.library = MidiLibrary()
        self.preferences_store = PreferencesStore()
        self.preferences = self.preferences_store.load()
        self.converter = MidiConverter()
        self.performer = MidiPerformer()
        self.performer.hotkey_label = self.preferences.hotkey
        self._hotkey_registered = False
        self._f12_hotkey = F12Hotkey(self)
        self._f12_hotkey.pressed.connect(self._f12_pressed, Qt.ConnectionType.QueuedConnection)
        self._closing = False
        self._track_dialog = None
        self.audition = MidiAudition(self)
        self.overlay = PlaybackOverlay(self)
        self.overlay.set_enabled(self.preferences.overlay_enabled)

        self._build_ui()
        self._connect_signals()
        self._refresh_library()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)
        page = QVBoxLayout(root)
        page.setContentsMargins(32, 24, 32, 24)
        page.setSpacing(12)
        page.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Delta Harmonica")
        title.setObjectName("appTitle")
        self.author = QLabel()
        self.author.setOpenExternalLinks(True)
        self.author.setObjectName("muted")
        titles.addWidget(title)
        author_row = QHBoxLayout()
        author_row.setSpacing(6)
        author_row.addWidget(BilibiliIcon())
        author_row.addWidget(self.author)
        author_row.addStretch()
        titles.addLayout(author_row)
        header.addLayout(titles)
        header.addStretch()
        self.theme_button = ThemeButton()
        self.theme_button.clicked.connect(self._toggle_theme)
        header.addWidget(self.theme_button, 0, Qt.AlignmentFlag.AlignTop)
        header.addSpacing(8)
        self.ready_badge = QLabel(f"●  {self.preferences.hotkey} 热键已就绪")
        self.ready_badge.setObjectName("readyBadge")
        header.addWidget(self.ready_badge, 0, Qt.AlignmentFlag.AlignTop)
        page.addLayout(header)

        search_card = QFrame()
        search_card.setObjectName("searchCard")
        search_layout = QHBoxLayout(search_card)
        search_layout.setContentsMargins(18, 13, 18, 13)
        search_label = QLabel("找 MIDI")
        search_label.setObjectName("searchTitle")
        search_layout.addWidget(search_label)
        self.midi_search = QLineEdit()
        self.midi_search.setPlaceholderText("输入歌曲名或歌手")
        self.midi_search.setClearButtonEnabled(True)
        search_layout.addWidget(self.midi_search, 1)
        self.midishow_button = QPushButton("搜索 MIDIShow")
        search_layout.addWidget(self.midishow_button)
        page.addWidget(search_card)

        import_row = QHBoxLayout()
        import_row.setSpacing(14)
        self.drop_zone = DropZone()
        self.drop_zone.setMinimumHeight(72)
        import_row.addWidget(self.drop_zone, 1)
        self.import_button = QPushButton("选择 MIDI 曲谱")
        self.import_button.setObjectName("primary")
        self.import_button.setMinimumSize(196, 72)
        import_row.addWidget(self.import_button)
        page.addLayout(import_row)
        section_row = QHBoxLayout()
        section_title = QLabel("我的曲谱")
        section_title.setObjectName("sectionTitle")
        section_row.addWidget(section_title)
        section_row.addStretch()
        self.remove_button = QPushButton("从列表移除")
        self.remove_button.setEnabled(False)
        section_row.addWidget(self.remove_button)
        page.addLayout(section_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("歌曲", "文件", "当前音轨", "大小", "状态"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(226)
        self.table.setColumnHidden(1, True)
        self.table.setColumnHidden(3, True)
        page.addWidget(self.table, 1)

        self.song_hint = QLabel("")
        self.song_hint.setObjectName("muted")
        self.song_hint.setWordWrap(True)
        page.addWidget(self.song_hint)

        controls = QFrame()
        controls.setObjectName("controlCard")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(20, 16, 20, 16)

        self.preview_button = QPushButton("试听")
        self.preview_button.setObjectName("primary")
        self.preview_button.setToolTip("试听口琴适配后的旋律，使用钢琴合成音色")
        controls_layout.addWidget(self.preview_button)
        controls_layout.addSpacing(16)
        controls_layout.addWidget(QLabel("播放速度"))
        self.speed = SpeedControl()
        controls_layout.addWidget(self.speed)
        controls_layout.addStretch()
        self.analyze_button = QPushButton("选择音轨")
        controls_layout.addWidget(self.analyze_button)
        self.settings_button = QPushButton("更多设置")
        self.settings_button.setCheckable(True)
        controls_layout.addWidget(self.settings_button)
        page.addWidget(controls)
        self.settings_panel = QFrame()
        self.settings_panel.setObjectName("controlCard")
        settings_layout = QHBoxLayout(self.settings_panel)
        settings_layout.setContentsMargins(20, 12, 20, 12)
        settings_layout.addWidget(QLabel("启停热键"))
        self.hotkey = QComboBox()
        self.hotkey.addItems(list(HOTKEYS))
        self.hotkey.setCurrentText(self.preferences.hotkey)
        settings_layout.addWidget(self.hotkey)
        settings_layout.addWidget(QLabel("启动延时"))
        self.countdown = AccentSpinBox()
        self.countdown.setRange(0, 30)
        self.countdown.setSuffix(" 秒")
        self.countdown.setValue(self.preferences.delay_seconds)
        settings_layout.addWidget(self.countdown)
        self.overlay_toggle = QCheckBox("局内悬浮提示")
        self.overlay_toggle.setChecked(self.preferences.overlay_enabled)
        self.overlay_toggle.setToolTip("显示在软件所在屏幕右上角，鼠标穿透；建议游戏使用无边框窗口")
        settings_layout.addWidget(self.overlay_toggle)
        settings_layout.addStretch()
        page.addWidget(self.settings_panel)
        self.settings_panel.hide()

        self.playback_details = QLabel("")
        self.playback_details.setObjectName("muted")
        self.playback_details.setWordWrap(True)
        page.addWidget(self.playback_details)
        self.playback_details.hide()
        self.pending_settings = QLabel("")
        self.pending_settings.setObjectName("muted")
        page.addWidget(self.pending_settings)
        self.pending_settings.hide()

        status_row = QHBoxLayout()
        self.status_label = QLabel(
            f"选中曲谱可试听；切到游戏按 {self.preferences.hotkey} 开始/停止"
        )
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        status_row.addWidget(self.status_label, 2)
        status_row.addWidget(self.progress, 1)
        page.addLayout(status_row)

        self._apply_theme()

    def _apply_theme(self) -> None:
        theme = self.preferences.theme
        self.setStyleSheet(stylesheet(theme))
        self.theme_button.set_theme(theme)
        color = "#315dc8" if theme == "light" else "#8fa8ff"
        self.author.setText(
            f'创作者：<a style="color:{color};text-decoration:none" '
            'href="https://space.bilibili.com/501585047">沙拉Sarada</a>'
        )

    def _toggle_theme(self) -> None:
        self.preferences.theme = "light" if self.preferences.theme == "dark" else "dark"
        self._apply_theme()
        self._persist_preferences()

    def _connect_signals(self) -> None:
        self.import_button.clicked.connect(self._choose_files)
        self.drop_zone.files_dropped.connect(self._import_files)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.remove_button.clicked.connect(self._remove_selected)
        self.analyze_button.clicked.connect(self._convert_selected)
        self.countdown.valueChanged.connect(self._save_settings)
        self.speed.speed_changed.connect(self._save_song_speed)
        self.speed.invalid_input.connect(self.status_label.setText)
        self.overlay_toggle.toggled.connect(self._overlay_changed)
        self.settings_button.toggled.connect(self.settings_panel.setVisible)
        self.preview_button.clicked.connect(self._toggle_preview)
        self.audition.state_changed.connect(self.status_label.setText)
        self.audition.failed.connect(lambda message: self.status_label.setText(f"试听失败 · {message}"))
        self.audition.finished.connect(lambda: self.preview_button.setText("试听"))
        self.hotkey.currentTextChanged.connect(self._hotkey_changed)
        self.midishow_button.clicked.connect(self._search_midishow)
        self.midi_search.returnPressed.connect(self._search_midishow)
        self.performer.state_changed.connect(self.status_label.setText)
        self.performer.state_changed.connect(self.overlay.set_state)
        self.performer.timeline_started.connect(self.overlay.start_timeline)
        self.performer.progress_changed.connect(lambda value: self.progress.setValue(round(value * 1000)))
        self.performer.diagnostics_changed.connect(self._show_diagnostics)
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
                self._toggle_performance()
                return True, 0
        return super().nativeEvent(event_type, message)

    def _toggle_performance(self) -> None:
        if self._closing or self._track_dialog is not None:
            return
        if self.performer.is_running:
            self.performer.stop()
        else:
            self._start_selected_from_hotkey()

    def _f12_pressed(self, generation: int) -> None:
        if (self._hotkey_registered and self.preferences.hotkey == "F12"
                and generation == self._f12_hotkey.generation):
            self._toggle_performance()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.audition.stop()
        if self._track_dialog is not None:
            self._track_dialog.reject()
        if self.performer.is_running:
            self._closing = True
            self.performer.shutdown()
            event.ignore()
            return
        self._unregister_hotkey()
        self.overlay.close()
        event.accept()

    def _register_hotkey(self) -> None:
        if sys.platform != "win32":
            return
        self._unregister_hotkey()
        vk_code = HOTKEYS[self.preferences.hotkey]
        if self.preferences.hotkey == "F12":
            self._hotkey_registered = self._f12_hotkey.register()
        else:
            self._hotkey_registered = bool(
                ctypes.windll.user32.RegisterHotKey(int(self.winId()), HOTKEY_ID, MOD_NOREPEAT, vk_code)
            )
        if not self._hotkey_registered:
            self.ready_badge.setText(f"●  {self.preferences.hotkey} 热键不可用")
            self.status_label.setText(
                f"{self.preferences.hotkey} 被其他程序占用，请换一个启停热键"
            )
        else:
            self.ready_badge.setText(f"●  {self.preferences.hotkey} 热键已就绪")

    def _unregister_hotkey(self) -> None:
        hooked = self._f12_hotkey.active
        self._f12_hotkey.close()
        if self._hotkey_registered and not hooked and sys.platform == "win32":
            ctypes.windll.user32.UnregisterHotKey(int(self.winId()), HOTKEY_ID)
        self._hotkey_registered = False

    def _hotkey_changed(self, hotkey: str) -> None:
        self.preferences.hotkey = hotkey
        self.performer.hotkey_label = hotkey
        song = self._selected_song()
        preset = find_preset(song.id) if song else None
        if preset:
            self.song_hint.setText(preset.hint.replace("F6", hotkey))
        saved = self._persist_preferences()
        self.ready_badge.setText(f"●  {hotkey} 热键已就绪")
        if self.isVisible():
            self._register_hotkey()
            if self._hotkey_registered and saved:
                self.status_label.setText(f"启停热键已改为 {hotkey}")

    def _search_midishow(self) -> None:
        query = self.midi_search.text().strip()
        url = (f"https://www.midishow.com/search/result?q={quote_plus(query)}"
               if query else "https://www.midishow.com/")
        if not QDesktopServices.openUrl(QUrl(url)):
            self.status_label.setText("无法打开浏览器，请访问 midishow.com")

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 MIDI 曲谱", "", IMPORT_FILTER)
        if paths:
            self._import_files(paths)

    def _import_files(self, paths: list[str]) -> None:
        if self.performer.is_running:
            self.status_label.setText("请先停止演奏，再导入 MIDI")
            return
        self.audition.stop()
        try:
            imported, errors = self.library.import_files(paths)
        except OSError as exc:
            self.status_label.setText(f"无法保存曲谱列表：{exc}")
            return
        self._refresh_library()
        if imported:
            conversion_errors: list[str] = []
            converted_count = 0
            for song in imported:
                try:
                    if self._convert_song(song) is not None:
                        converted_count += 1
                except Exception as exc:
                    song.status = "转换失败"
                    conversion_errors.append(f"{song.title}：{exc}")
                    try:
                        self.library.update(song)
                    except OSError as save_error:
                        conversion_errors.append(f"无法保存曲谱状态：{save_error}")
            self._refresh_library()
            self._select_song(imported[-1].id)
            if not conversion_errors:
                if converted_count:
                    self.status_label.setText(
                        f"已导入并转换 {converted_count} 首 MIDI · 切到游戏按 "
                        f"{self.preferences.hotkey} 开始/停止"
                    )
                else:
                    self.status_label.setText("已导入 MIDI，请选择主旋律音轨")
            else:
                errors.extend(conversion_errors)
        if errors:
            QMessageBox.information(self, "导入或转换未完成", "\n".join(errors))

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
                QTableWidgetItem("内置" if song.is_builtin else source.name),
                QTableWidgetItem(song.track_name or "未选择"),
                QTableWidgetItem("—" if song.is_builtin else format_size(song.file_size)),
                QTableWidgetItem(status),
            )
            for column, item in enumerate(values):
                item.setToolTip(item.text())
                self.table.setItem(row, column, item)
        if songs and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)
        else:
            self._selection_changed()

    def _selection_changed(self) -> None:
        self.audition.stop()
        selected = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        enabled = bool(selected)
        song = self._selected_song() if enabled else None
        self.remove_button.setEnabled(bool(song) and not self.performer.is_running)
        self.preview_button.setEnabled(enabled and not self.performer.is_running)
        preset = find_preset(song.id) if song else None
        self.song_hint.setText(preset.hint.replace("F6", self.preferences.hotkey) if preset else "")
        self.song_hint.setVisible(preset is not None)
        self.song_hint.setToolTip(preset.hint.replace("F6", self.preferences.hotkey) if preset else "")
        is_midi = bool(song and not song.is_builtin and Path(song.source_path).suffix.lower() in {".mid", ".midi"})
        busy = self.performer.is_running
        self.analyze_button.setEnabled(bool(song and song.exists and is_midi) and not busy)
        self.import_button.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.hotkey.setEnabled(not busy)
        self.speed.setEnabled(song is not None)
        self.speed.set_percent(song.speed_percent if song else 100)

    def _selected_song(self) -> MidiSong | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return None
        song_id = item.data(Qt.ItemDataRole.UserRole)
        return next((song for song in self.library.songs if song.id == song_id), None)

    def _remove_selected(self) -> None:
        if self.performer.is_running:
            self.status_label.setText("请先停止演奏，再移除曲谱")
            return
        song = self._selected_song()
        if song is None:
            return
        try:
            self.library.remove(song.id)
        except OSError as exc:
            self.status_label.setText(f"无法保存曲谱列表：{exc}")
            return
        self._refresh_library()
        self.status_label.setText("已从列表移除；原 MIDI 文件未删除")

    def _convert_selected(self) -> None:
        if self.performer.is_running:
            self.status_label.setText("请先按启停热键停止演奏，再选择音轨")
            return
        self.audition.stop()
        song = self._selected_song()
        if song is None:
            return
        if song.is_builtin:
            return
        self.progress.setValue(0)
        try:
            result = self._convert_song(song)
        except Exception as exc:
            song.status = "转换失败"
            try:
                self.library.update(song)
            except OSError as save_error:
                exc = OSError(f"{exc}；无法保存曲谱状态：{save_error}")
            self._refresh_library()
            self.status_label.setText(f"转换失败：{exc}")
            QMessageBox.warning(self, "转换失败", str(exc))
            return
        if result is None:
            self.status_label.setText("未更改音轨选择")
            return
        self._refresh_library()
        self._select_song(song.id)
        shift = f"+{result.transpose}" if result.transpose >= 0 else str(result.transpose)
        self.status_label.setText(
            f"转换完成：{len(result.notes)} 个音符 · {result.track_name} · 移调 {shift} 半音"
        )
        self.progress.setValue(1000)

    def _convert_song(
        self,
        song: MidiSong,
    ) -> MidiConversionResult | None:
        source = Path(song.source_path)
        analysis = self.converter.analyze(source)
        self.audition.stop()
        dialog = TrackSelectionDialog(analysis, self, speed_percent=song.speed_percent)
        for row, candidate in enumerate(analysis.candidates):
            if (candidate.track_index, candidate.channel) == (song.track_index, song.channel):
                dialog.table.selectRow(row)
                break
        self._track_dialog = dialog
        try:
            decision = dialog.exec()
        finally:
            dialog.preview.stop()
            self._track_dialog = None
        if decision != QDialog.DialogCode.Accepted:
            if not song.converted_path:
                song.status = "等待选择音轨"
                self.library.update(song)
            dialog.deleteLater()
            return None
        selected = dialog.selected_candidate()
        dialog.deleteLater()

        result = self.converter.convert_analysis(
            analysis,
            track_index=selected.track_index,
            channel=selected.channel,
        )
        target = converted_directory() / f"{song.id}.json"
        save_performance(target, result.notes, source=song.source_path, transpose=result.transpose)
        song.converted_path = str(target)
        song.track_index = result.track_index
        song.channel = result.channel
        song.track_name = result.track_name
        song.selection_confidence = "用户选择"
        shift = f"+{result.transpose}" if result.transpose >= 0 else str(result.transpose)
        song.status = f"可演奏 · {len(result.notes)} 音 · 移调 {shift}"
        self.library.update(song)
        return result

    def _select_song(self, song_id: str) -> None:
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == song_id:
                self.table.selectRow(row)
                return

    def _start_selected_from_hotkey(self) -> None:
        self.audition.stop()
        song = self._selected_song()
        if song is None:
            self.status_label.setText("请先在列表中选择一首歌曲")
            return
        preset = find_preset(song.id)
        if preset:
            notes, keys = preset.performance()
            self._start_performance(notes, keys=keys)
            return
        if not song.converted_path or not Path(song.converted_path).is_file():
            self.status_label.setText("所选歌曲还没有完成转换")
            return
        try:
            self._start_performance(load_performance(song.converted_path))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self._performance_failed(f"无法读取曲谱：{exc}")

    def _start_performance(self, notes, *, keys=None) -> None:  # type: ignore[no-untyped-def]
        if self.performer.is_running:
            return
        self.speed.commit_text()
        self.speed.popup.hide()
        self.progress.setValue(0)
        timing = PerformanceTiming.for_speed(self.speed.percent)
        self.pending_settings.clear()
        self.pending_settings.hide()
        self.audition.stop()
        song = self._selected_song()
        duration = notes[-1].end * 100 / timing.speed_percent if notes else 0.0
        self.overlay.begin(song.title if song else "口琴演奏", timing.speed_percent,
                           self.preferences.hotkey, duration)
        self.performer.start(notes, self.preferences.delay_seconds, timing, keys=keys)
        self._selection_changed()

    def _toggle_preview(self) -> None:
        self.speed.commit_text()
        if self.audition.is_running:
            self.audition.stop()
            return
        if self.performer.is_running:
            self.status_label.setText("请先按启停热键停止演奏，再试听")
            return
        song = self._selected_song()
        if not song:
            return
        try:
            preset = find_preset(song.id)
            if preset:
                notes, keys = preset.performance()
            elif song.converted_path:
                notes, keys = load_performance(song.converted_path), None
            else:
                self.status_label.setText("请先选择音轨完成转换")
                return
            timing = PerformanceTiming.for_speed(self.speed.percent)
            self.audition.start(build_performance_schedule(notes, timing, keys))
            if self.audition.is_running:
                self.preview_button.setText("停止试听")
                self.pending_settings.clear()
                self.pending_settings.hide()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.status_label.setText(f"试听失败 · {exc}")


    def _show_diagnostics(self, text: str) -> None:
        diagnostic = self.performer.diagnostics
        risk = bool(diagnostic and (diagnostic.short_notes or diagnostic.tight_gaps or diagnostic.short_modifier_leads))
        self.playback_details.setText("音符较密，可能漏音；可降低倍速。" if risk else "")
        self.playback_details.setToolTip(text)
        self.playback_details.setVisible(risk)

    def _performance_failed(self, message: str) -> None:
        self.status_label.setText(f"演奏失败 · {message}")
        self.overlay.failed()

    def _performance_finished(self) -> None:
        self._selection_changed()
        if self._closing:
            self._closing = False
            if not (self.performer.diagnostics and self.performer.diagnostics.cleanup_failed):
                self.close()


    def _save_settings(self) -> None:
        self.preferences.delay_seconds = self.countdown.value()
        self._persist_preferences()
        if self.performer.is_running or self.audition.is_running:
            self.pending_settings.setText("修改将在下次开始生效")
            self.pending_settings.show()

    def _save_song_speed(self, percent: int) -> None:
        song = self._selected_song()
        if song is None:
            return
        try:
            self.library.update(replace(song, speed_percent=percent))
        except OSError as exc:
            self.speed.set_percent(song.speed_percent)
            self.status_label.setText(f"未能保存这首歌的倍速：{exc}")
            return
        if self.performer.is_running or self.audition.is_running:
            self.pending_settings.setText("本曲倍速已保存，下次开始生效")
            self.pending_settings.show()

    def _overlay_changed(self, enabled: bool) -> None:
        self.preferences.overlay_enabled = enabled
        self.overlay.set_enabled(enabled)
        self._persist_preferences()

    def _persist_preferences(self) -> bool:
        try:
            self.preferences_store.save(self.preferences)
        except OSError as exc:
            self.status_label.setText(f"设置已在本次运行生效，但未能保存：{exc}")
            return False
        return True


NOTE_NAMES = ("C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B")


def _note_name(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def _format_duration(seconds: float) -> str:
    total = max(0, round(seconds))
    minutes, remaining = divmod(total, 60)
    return f"{minutes}:{remaining:02d}"


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"
