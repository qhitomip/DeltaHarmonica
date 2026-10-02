"""One window per user-data directory; repeat launches activate that window."""
import hashlib
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, directory: Path, parent=None):
        super().__init__(parent)
        self.lock = QLockFile(str(directory / 'instance.lock'))
        self.lock.setStaleLockTime(0)  # A live long-running process is not stale.
        self.name = 'DeltaHarmonica-' + hashlib.sha256(str(directory.resolve()).lower().encode()).hexdigest()[:20]
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._connected)
        self.primary = False

    def acquire(self) -> bool:
        if not self.lock.tryLock(0):
            if self.lock.error() != QLockFile.LockError.LockFailedError:
                raise OSError('无法访问软件数据目录，请检查磁盘空间和写入权限')
            client = QLocalSocket()
            client.connectToServer(self.name)
            client.waitForConnected(1500)
            client.disconnectFromServer()
            return False
        # Removing a stale pipe is safe only while holding the exclusive lock.
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise OSError('无法建立软件窗口通信：' + self.server.errorString())
        self.primary = True
        return True

    def _connected(self):
        while self.server.hasPendingConnections():
            client = self.server.nextPendingConnection()
            client.close()
            client.deleteLater()
        self.activated.emit()

    def close(self):
        if self.primary:
            self.server.close()
            self.lock.unlock()
            self.primary = False
