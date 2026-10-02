"""Compact speed button with presets, exact entry and repeatable adjustment."""
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QPoint, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QPainter, QPalette, QPen, QPolygon
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from .settings import MAX_SPEED, MIN_SPEED, SPEED_OPTIONS


class _SpeedPanel(QFrame):
    dismissed = Signal()

    def hideEvent(self, event) -> None:
        self.dismissed.emit()
        super().hideEvent(event)


class SpeedControl(QPushButton):
    speed_changed = Signal(int)
    invalid_input = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.percent = 100
        self.setMinimumWidth(112)
        self.setToolTip("每首歌单独记忆倍速；播放中修改下次生效")
        self.popup = _SpeedPanel(self, Qt.WindowType.Popup)
        self.popup.setObjectName("speedPanel")
        self.popup.setFixedWidth(300)
        layout = QVBoxLayout(self.popup)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(QLabel("常用速度"))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.preset_buttons = {}
        for index, (label, percent) in enumerate(SPEED_OPTIONS):
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=percent: self._choose(value))
            self.preset_buttons[percent] = button
            grid.addWidget(button, index // 3, index % 3)
        layout.addLayout(grid)
        layout.addWidget(QLabel("精细调节 · 0.25～1.50×"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.decrease = QPushButton("−")
        self.increase = QPushButton("＋")
        self.editor = QLineEdit()
        self.editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor.setMaxLength(16)
        self.editor.setAccessibleName("自定义播放倍速")
        self.editor.setToolTip("输入倍速后按回车确认，最多两位小数")
        for button, delta, title in ((self.decrease, -1, "减小倍速"), (self.increase, 1, "增大倍速")):
            button.setFixedWidth(40)
            button.setAutoRepeat(True)
            button.setAutoRepeatDelay(400)
            button.setAutoRepeatInterval(70)
            button.setAccessibleName(title)
            button.clicked.connect(lambda checked=False, step=delta: self._step(step))
        row.addWidget(self.decrease)
        row.addWidget(self.editor, 1)
        row.addWidget(self.increase)
        layout.addLayout(row)
        self.reset_button = QPushButton("恢复原速")
        self.reset_button.clicked.connect(lambda: self._choose(100))
        layout.addWidget(self.reset_button)
        self.set_percent(100)
        self.clicked.connect(self.show_popup)
        self.editor.editingFinished.connect(self.commit_text)
        self.editor.returnPressed.connect(self._accept_text)
        self.popup.dismissed.connect(self._dismissed)

    @staticmethod
    def label(percent: int) -> str:
        value = f"{percent / 100:.2f}".rstrip("0")
        return (value + "0" if value.endswith(".") else value) + "×"

    def set_percent(self, percent: int) -> None:
        self.percent = max(MIN_SPEED, min(MAX_SPEED, int(percent)))
        with QSignalBlocker(self.editor):
            self.editor.setText(self.label(self.percent))
        self.setText(self.label(self.percent) + "    ")
        for value, button in self.preset_buttons.items():
            button.setChecked(value == self.percent)
        self.decrease.setEnabled(self.percent > MIN_SPEED)
        self.increase.setEnabled(self.percent < MAX_SPEED)

    def _commit(self, percent: int) -> None:
        percent = max(MIN_SPEED, min(MAX_SPEED, percent))
        changed = percent != self.percent
        self.set_percent(percent)
        if changed:
            self.speed_changed.emit(percent)

    def _choose(self, percent: int) -> None:
        self._commit(percent)
        self.popup.hide()

    def _step(self, delta: int) -> None:
        self.commit_text()
        self._commit(self.percent + delta)

    def commit_text(self) -> bool:
        try:
            text = self.editor.text().strip().lower().removesuffix("x").removesuffix("×").strip()
            percent = Decimal(text) * 100
            if (not percent.is_finite() or not MIN_SPEED <= percent <= MAX_SPEED
                    or percent != percent.to_integral_value()):
                raise ValueError
            self._commit(int(percent))
            return True
        except (InvalidOperation, ValueError):
            self.set_percent(self.percent)
            self.invalid_input.emit("请输入 0.25～1.50 的倍速，最多两位小数")
            return False

    def _accept_text(self) -> None:
        if self.commit_text():
            self.popup.hide()

    def _dismissed(self) -> None:
        self.decrease.setDown(False)
        self.increase.setDown(False)
        self.commit_text()

    def show_popup(self) -> None:
        self.popup.adjustSize()
        rect = self.screen().availableGeometry()
        below = self.mapToGlobal(QPoint(0, self.height() + 6))
        y = below.y()
        if y + self.popup.height() > rect.bottom() + 1:
            y = self.mapToGlobal(QPoint(0, -self.popup.height() - 6)).y()
        x = max(rect.left(), min(below.x(), rect.right() + 1 - self.popup.width()))
        self.popup.move(x, max(rect.top(), y))
        self.popup.show()
        self.editor.setFocus(Qt.FocusReason.PopupFocusReason)
        self.editor.selectAll()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText), 1.5))
        x, y = self.width() - 15, self.height() // 2
        painter.drawPolyline(QPolygon([QPoint(x - 4, y - 2), QPoint(x, y + 2), QPoint(x + 4, y - 2)]))
