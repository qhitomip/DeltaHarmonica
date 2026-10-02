"""Application themes and a vector-drawn, font-independent theme switch."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QPushButton


class ThemeButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("themeButton")
        self.setFixedSize(38, 38)
        self.set_theme("dark")

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        action = "切换为浅色" if theme == "dark" else "切换为深色"
        self.setToolTip(action)
        self.setAccessibleName(action)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        painter.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if self.theme == "dark":
            painter.drawEllipse(-4, -4, 8, 8)
            for _ in range(8):
                painter.drawLine(0, -8, 0, -10)
                painter.rotate(45)
        else:
            moon, cutout = QPainterPath(), QPainterPath()
            moon.addEllipse(-8, -8, 16, 16)
            cutout.addEllipse(-2, -10, 16, 16)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(moon.subtracted(cutout))


def stylesheet(theme: str) -> str:
    return DARK_STYLESHEET + (LIGHT_OVERRIDES if theme == "light" else "")


DARK_STYLESHEET = """
QWidget {
    background: #0b1020;
    color: #edf2ff;
    font-family: "Microsoft YaHei UI";
    font-size: 14px;
}
QWidget#appRoot { background: #0b1020; }
QLabel#appTitle { font-size: 28px; font-weight: 700; }
QLabel#dialogTitle { font-size: 22px; font-weight: 700; }
QLabel#sectionTitle { font-size: 18px; font-weight: 650; }
QLabel#dropTitle { font-size: 18px; font-weight: 650; }
QLabel#muted { color: #8f9bb3; }
QLabel#searchTitle { color: #dce6ff; font-weight: 650; }
QLabel#readyBadge {
    background: #15213c;
    color: #a9b9e8;
    border: 1px solid #2e3b61;
    border-radius: 13px;
    padding: 8px 13px;
}
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
    selection-color: #edf2ff;
}
QHeaderView::section {
    background: #151f36;
    color: #aebbd6;
    border: none;
    border-bottom: 1px solid #2a3654;
    padding: 10px;
}
QTableWidget::item { padding: 9px; }
QTableWidget::item:selected { color: #edf2ff; background: #263a72; }
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
QSpinBox::up-arrow, QSpinBox::down-arrow { image: none; }
QSpinBox::up-button, QSpinBox::down-button {
    background: #3b5393;
    border-left: 1px solid #6682df;
    width: 22px;
}
QSpinBox::up-button { border-top-right-radius: 6px; }
QSpinBox::down-button { border-bottom-right-radius: 6px; }
QPushButton:checked { background: #314879; border-color: #8198ff; }
QLabel { background: transparent; }
QScrollArea#pageScroll { border: none; background: #0b1020; }
QScrollBar:vertical { background: #0f1628; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #34446e; min-height: 24px; border-radius: 5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QProgressBar { background: #131c31; border: none; border-radius: 3px; max-height: 6px; }
QProgressBar::chunk { background: #5b75ff; border-radius: 3px; }

            QFrame#speedPanel { background: #131d32; border: 1px solid #526b9f; border-radius: 10px; }
            QFrame#speedPanel QLabel { background: transparent; color: #bac8e2; font-size: 13px; }
            QFrame#speedPanel QPushButton { background: #213353; color: #edf2ff; border: 1px solid #3c547e;
                border-radius: 6px; padding: 8px 6px; font-size: 14px; }
            QFrame#speedPanel QPushButton:hover { background: #30496e; border-color: #809fff; }
            QFrame#speedPanel QPushButton:checked { background: #263e66; border-color: #13c6ff; color: #54d9ff; }
            QFrame#speedPanel QPushButton:disabled { color: #687892; background: #172239; }
            QFrame#speedPanel QLineEdit { background: #0d1629; color: #edf2ff; border: 1px solid #617eb9;
                border-radius: 6px; padding: 8px; font-size: 15px; }

QPushButton#themeButton { padding: 0; border-radius: 10px; }
QCheckBox { background: transparent; }
QToolTip { background: #1b2541; color: #edf2ff; border: 1px solid #52658f; padding: 5px; }
"""

# Layout and typography are shared; only colors change in the light theme.
LIGHT_OVERRIDES = """
QWidget { background: #f3f5fa; color: #25324b; }
QWidget#appRoot, QScrollArea#pageScroll { background: #f3f5fa; }
QLabel { background: transparent; }
QLabel#muted { color: #5e6d85; }
QLabel#searchTitle { color: #25324b; }
QLabel#readyBadge { background: #eaf0ff; color: #315595; border-color: #c9d6ef; }
QFrame#dropZone { background: #ffffff; border-color: #a8b7d2; }
QFrame#controlCard, QFrame#searchCard { background: #ffffff; border-color: #d6deec; }
QPushButton { background: #edf2fb; color: #2c405f; border-color: #c3d0e6; }
QPushButton:hover { background: #e0e9ff; border-color: #879fd8; }
QPushButton:checked { background: #dbe6ff; border-color: #7b96d8; }
QPushButton:disabled { background: #f0f2f6; color: #7a879b; border-color: #dfe4ee; }
QPushButton#primary { background: #4663e6; color: #ffffff; border-color: #4663e6; }
QPushButton#primary:hover { background: #3854d4; }
QPushButton#primary:disabled { background: #dfe5f7; color: #7a879b; border-color: #d1d9ee; }
QTableWidget { background: #ffffff; alternate-background-color: #f7f9fd; border-color: #d6deec;
    gridline-color: #e2e7f1; selection-background-color: #dbe6ff; selection-color: #203c78; }
QHeaderView::section { background: #eaf0fa; color: #425572; border-bottom-color: #cfd9e9; }
QTableWidget::item:selected { color: #203c78; background: #dbe6ff; }
QLineEdit, QComboBox, QSpinBox { background: #ffffff; color: #25324b; border-color: #a9bcdd; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #526fe0; }
QComboBox QAbstractItemView { background: #ffffff; color: #25324b;
    selection-background-color: #dbe6ff; selection-color: #203c78; }
QSpinBox::up-button, QSpinBox::down-button { background: #dbe6fc; border-left-color: #a9bcdd; }
QScrollBar:vertical { background: #edf1f8; }
QScrollBar::handle:vertical { background: #b5c4df; }
QProgressBar { background: #e1e7f2; }
QProgressBar::chunk { background: #526ee5; }
QToolTip { background: #ffffff; color: #25324b; border-color: #a9bcdd; }
QFrame#speedPanel { background: #ffffff; border-color: #a9bcdd; }
QFrame#speedPanel QLabel { color: #5e6d85; }
QFrame#speedPanel QPushButton { background: #edf2fb; color: #2c405f; border-color: #c3d0e6; }
QFrame#speedPanel QPushButton:hover { background: #e0e9ff; border-color: #879fd8; }
QFrame#speedPanel QPushButton:checked { background: #dbe6ff; color: #264eb0; border-color: #526fe0; }
QFrame#speedPanel QPushButton:disabled { background: #f0f2f6; color: #7a879b; border-color: #dfe4ee; }
QFrame#speedPanel QLineEdit { background: #f7f9fd; color: #25324b; border-color: #a9bcdd; }
"""
