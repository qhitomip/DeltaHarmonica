from dataclasses import replace
import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from delta_harmonica.performer import PerformanceTiming
from delta_harmonica.speed_control import SpeedControl
from delta_harmonica.storage import MidiLibrary
from delta_harmonica.ui import MainWindow


class SpeedPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.control = SpeedControl()
        self.control.show()

    def tearDown(self):
        self.control.popup.hide()
        self.control.close()
        self.app.processEvents()

    def test_preset_dismisses_but_steps_remain_open_and_bounds_hold(self):
        self.control.click()
        self.app.processEvents()
        self.assertTrue(self.control.popup.isVisible())
        self.control.preset_buttons[75].click()
        self.assertEqual(75, self.control.percent)
        self.assertFalse(self.control.popup.isVisible())
        self.control.click()
        self.control.increase.click()
        self.assertEqual(76, self.control.percent)
        self.assertTrue(self.control.popup.isVisible())
        self.control.set_percent(150)
        self.control.increase.click()
        self.assertEqual(150, self.control.percent)
        self.assertFalse(self.control.increase.isEnabled())
        self.control.set_percent(25)
        self.assertFalse(self.control.decrease.isEnabled())
        self.control.reset_button.click()
        self.assertEqual(100, self.control.percent)
        self.assertFalse(self.control.popup.isVisible())

    def test_return_outside_close_and_hold_do_not_leave_repeat_running(self):
        self.control.click()
        self.control.editor.setText('0.92x')
        QTest.keyClick(self.control.editor, Qt.Key.Key_Return)
        self.assertEqual(92, self.control.percent)
        self.assertFalse(self.control.popup.isVisible())
        self.control.click()
        self.control.editor.setText('0.93x')
        QTest.mouseClick(self.control.popup, Qt.MouseButton.LeftButton, pos=QPoint(-10, -10))
        self.assertFalse(self.control.popup.isVisible())
        self.assertEqual(93, self.control.percent)
        self.control.click()
        QTest.mousePress(self.control.increase, Qt.MouseButton.LeftButton)
        QTest.qWait(650)
        self.assertGreater(self.control.percent, 94)
        self.control.popup.hide()
        value = self.control.percent
        QTest.qWait(180)
        self.assertEqual(value, self.control.percent)
        QTest.mouseRelease(self.control.increase, Qt.MouseButton.LeftButton)

    def test_stored_speed_and_engine_are_limited_and_creator_is_clickable(self):
        with TemporaryDirectory() as temp, patch.dict(os.environ, LOCALAPPDATA=temp), \
                patch.object(MainWindow, '_register_hotkey'), patch.object(MainWindow, '_unregister_hotkey'):
            library = MidiLibrary()
            library.update(replace(library.songs[0], speed_percent=300))
            self.assertEqual(150, MidiLibrary().songs[0].speed_percent)
            self.assertEqual(150, PerformanceTiming.for_speed(300).speed_percent)
            window = MainWindow()
            try:
                author = next(label for label in window.findChildren(QLabel) if '创作者：' in label.text())
                self.assertEqual(1, author.text().count('<a '))
                self.assertIn('沙拉Sarada', author.text())
                self.assertIn('https://space.bilibili.com/501585047', author.text())
                self.assertTrue(author.openExternalLinks())
            finally:
                window.close()
