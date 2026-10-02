"""Non-activating desktop status overlay; never reads or modifies the game."""
import math
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget


class PlaybackOverlay(QWidget):
    def __init__(self, parent=None, *, clock=time.perf_counter):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("Delta Harmonica 状态")
        self.setFixedWidth(350)
        self.enabled = True
        self.session_active = False
        self.song_title = ""
        self.speed_percent = 100
        self.hotkey = "F6"
        self._clock = clock
        self._epoch = None
        self._terminal = False
        self.duration = 0.0
        self.elapsed = 0.0
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(100)
        self.progress_timer.timeout.connect(self._update_progress)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._dismiss)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("overlayPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        self.title_label = QLabel()
        self.state_label = QLabel()
        self.detail_label = QLabel()
        self.title_label.setObjectName("overlayTitle")
        self.state_label.setObjectName("overlayState")
        self.detail_label.setObjectName("overlayDetail")
        for label in (self.title_label, self.state_label, self.detail_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.title_label)
        status_row = QHBoxLayout()
        status_row.setSpacing(28)
        status_row.addWidget(self.state_label)
        timeline = QHBoxLayout()
        timeline.setSpacing(5)
        self.elapsed_label = QLabel("00:00")
        self.remaining_label = QLabel("-00:00")
        for label in (self.elapsed_label, self.remaining_label):
            label.setObjectName("overlayTime")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.elapsed_label.setToolTip("已播放时间")
        self.remaining_label.setToolTip("剩余时间")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setMinimumWidth(40)
        self.progress.setAccessibleName("演奏进度")
        timeline.addWidget(self.elapsed_label)
        timeline.addWidget(self.progress, 1)
        timeline.addWidget(self.remaining_label)
        status_row.addLayout(timeline, 1)
        layout.addLayout(status_row)
        layout.addWidget(self.detail_label)
        outer.addWidget(panel)
        self.setStyleSheet('''
            QWidget { font-family: "Microsoft YaHei UI"; font-size: 13px; background: transparent; }
            QFrame#overlayPanel { background: rgba(12, 19, 36, 226); border: 1px solid #405579; border-radius: 10px; }
            QLabel#overlayTitle { color: #edf2ff; font-weight: 600; }
            QLabel#overlayState { color: #70dfd3; font-size: 19px; font-weight: 600; }
            QLabel#overlayDetail { color: #bfcae0; }
            QLabel#overlayTime { color: #bfcae0; font-family: "Consolas"; font-size: 12px; }
            QProgressBar { background: #29354d; border: none; border-radius: 3px; }
            QProgressBar::chunk { background: #70dfd3; border-radius: 3px; }
        ''')

    def begin(self, title: str, speed_percent: int, hotkey: str, duration: float = 0.0) -> None:
        self.hide_timer.stop()
        self.progress_timer.stop()
        self._epoch = None
        self._terminal = False
        self.duration = max(0.0, duration)
        self.elapsed = 0.0
        self._render_progress()
        self.session_active = True
        self.song_title, self.speed_percent, self.hotkey = title, speed_percent, hotkey
        self.title_label.setText(self.title_label.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, 316))
        self.detail_label.setText(f"{speed_percent / 100:g}x  ·  {hotkey} 停止 / 取消")
        self.set_state("准备演奏")

    def start_timeline(self, epoch: float, duration: float) -> None:
        if not self.session_active or self._terminal:
            return
        self._epoch = epoch
        self.duration = max(0.0, duration)
        self._update_progress()
        self.progress_timer.start()

    def _update_progress(self) -> None:
        if self._epoch is not None:
            self.elapsed = min(self.duration, max(0.0, self._clock() - self._epoch))
        self._render_progress()

    def _render_progress(self) -> None:
        def stamp(seconds: int) -> str:
            minutes, seconds = divmod(seconds, 60)
            return f"{minutes:02d}:{seconds:02d}"

        self.elapsed_label.setText(stamp(int(self.elapsed)))
        self.remaining_label.setText("-" + stamp(math.ceil(max(0.0, self.duration - self.elapsed))))
        value = round(1000 * self.elapsed / self.duration) if self.duration > 0 else 0
        self.progress.setValue(value)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.hide()
        elif self.session_active:
            self._show_without_focus()

    def set_state(self, text: str) -> None:
        state = text.split(" · ", 1)[0]
        self.state_label.setText("正在停止" if state.startswith("正在停止") else state)
        if text.startswith(("正在停止", "已停止", "演奏完成", "演奏失败")):
            self._update_progress()
            self.progress_timer.stop()
            self._epoch = None
            self._terminal = True
            if text.startswith("演奏完成"):
                self.elapsed = self.duration
                self._render_progress()
        if text.startswith(("已停止", "演奏完成", "演奏失败")):
            self.detail_label.setText(f"{self.speed_percent / 100:g}x  ·  {self.hotkey} 从头开始")
            self.hide_timer.start(4000)
        if self.enabled and self.session_active:
            self._show_without_focus()

    def failed(self) -> None:
        self.set_state("演奏失败")
        self.detail_label.setText("返回软件查看原因")

    def _show_without_focus(self) -> None:
        screen = self.parentWidget().screen() if self.parentWidget() else QGuiApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        self.adjustSize()
        self.move(rect.right() - self.width() - 24, rect.top() + 24)
        self.show()

    def _dismiss(self) -> None:
        self.progress_timer.stop()
        self._epoch = None
        self.session_active = False
        self.hide()

    def closeEvent(self, event) -> None:
        self.hide_timer.stop()
        self.progress_timer.stop()
        self._epoch = None
        self.session_active = False
        super().closeEvent(event)
