from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from PySide6.QtWidgets import QApplication
from delta_harmonica.single_instance import SingleInstance


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_repeat_launch_activates_owner_and_can_reopen_after_close(self):
        with TemporaryDirectory() as directory:
            owner=SingleInstance(Path(directory));second=SingleInstance(Path(directory))
            activated=[]
            owner.activated.connect(lambda: activated.append(True))
            try:
                self.assertTrue(owner.acquire())
                self.assertFalse(second.acquire())
                deadline=time.perf_counter()+2
                while not activated and time.perf_counter()<deadline:
                    self.app.processEvents()
                    time.sleep(.005)
                self.assertTrue(activated)
                second.close()  # A non-owner must not release the owner's lock.
                self.assertFalse(second.acquire())
                owner.close()
                self.assertTrue(second.acquire())
            finally:
                owner.close();second.close()

    def test_different_profiles_do_not_share_locks(self):
        with TemporaryDirectory() as first,TemporaryDirectory() as second:
            a=SingleInstance(Path(first));b=SingleInstance(Path(second))
            try:
                self.assertTrue(a.acquire())
                self.assertTrue(b.acquire())
                self.assertNotEqual(a.name,b.name)
            finally:
                a.close();b.close()


if __name__=='__main__': unittest.main()
