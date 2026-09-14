import QtQuick
import Quickshell.Io

Item {
  id: root

  property var shell: null
  property bool shuttingDown: false

  function filePath(url) {
    var raw = String(url || "")
    if (raw.indexOf("file://") === 0) raw = raw.slice(7)
    try { raw = decodeURIComponent(raw) } catch (e) { return "" }
    return raw
  }

  readonly property string helperPath: filePath(Qt.resolvedUrl("scripts/controller-toggle.py"))

  Process {
    id: helper
    command: [root.helperPath]
    onExited: function(exitCode, exitStatus) {
      if (!root.shuttingDown) restartTimer.start()
    }
  }

  Timer {
    id: restartTimer
    interval: 1500
    repeat: false
    onTriggered: if (!root.shuttingDown) helper.running = true
  }

  Component.onCompleted: helper.running = helperPath !== ""
  Component.onDestruction: {
    shuttingDown = true
    restartTimer.stop()
    helper.running = false
  }
}
