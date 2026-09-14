import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.myagoo.controller-companion"
  ipcTarget: "io.github.myagoo.controller-companion"
  manageIpc: true

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root
  property bool mappingEnabled: false
  property bool stateInitialized: false
  property int mouseSpeed: 25
  property int scrollSpeed: 10
  property var mappings: []
  property var appOptions: []
  property string captureControl: ""

  function filePath(url) {
    var raw = String(url || "")
    if (raw.indexOf("file://") === 0) raw = raw.slice(7)
    try { raw = decodeURIComponent(raw) } catch (e) { return "" }
    return raw
  }

  readonly property string backend: filePath(Qt.resolvedUrl("scripts/controller-config.py"))
  readonly property string stateHome: Quickshell.env("XDG_STATE_HOME") || (Quickshell.env("HOME") + "/.local/state")
  readonly property string statePath: stateHome + "/omarchy/controller-companion/enabled"
  readonly property var controlLabels: ({
    a: "A", b: "B", x: "X", y: "Y", guide: "Guide",
    back: "Back / View", start: "Start / Menu",
    left_stick: "Left stick click", right_stick: "Right stick click",
    left_shoulder: "Left shoulder", right_shoulder: "Right shoulder",
    dpad_up: "D-pad up", dpad_right: "D-pad right", dpad_down: "D-pad down", dpad_left: "D-pad left",
    left_trigger: "Left trigger", right_trigger: "Right trigger"
  })
  readonly property var typeOptions: [
    { value: "key", label: "Key" },
    { value: "omarchy", label: "Omarchy shortcut" },
    { value: "app", label: "App" },
    { value: "mouse", label: "Mouse button" },
    { value: "disabled", label: "Disabled" }
  ]
  readonly property var mouseOptions: [
    { value: "left", label: "Left click" },
    { value: "middle", label: "Middle click" },
    { value: "right", label: "Right click" }
  ]
  readonly property var omarchyOptions: [
    { value: "menu", label: "Omarchy menu" },
    { value: "apps", label: "Apps menu" },
    { value: "keybindings", label: "Keybindings" },
    { value: "system", label: "System menu" },
    { value: "workspace-prev", label: "Previous workspace" },
    { value: "workspace-next", label: "Next workspace" },
    { value: "close-window", label: "Close window" },
    { value: "fullscreen", label: "Toggle fullscreen" }
  ]

  function keyName(event) {
    var key = event.key
    var name = ""
    if (key >= Qt.Key_A && key <= Qt.Key_Z) name = String.fromCharCode(key).toLowerCase()
    else if (key >= Qt.Key_0 && key <= Qt.Key_9) name = String.fromCharCode(key)
    else if (key >= Qt.Key_F1 && key <= Qt.Key_F35) name = "F" + String(key - Qt.Key_F1 + 1)
    else {
      var names = ({
        [Qt.Key_Return]: "Return", [Qt.Key_Enter]: "KP_Enter",
        [Qt.Key_Escape]: "Escape", [Qt.Key_Tab]: "Tab", [Qt.Key_Backtab]: "Tab",
        [Qt.Key_Backspace]: "BackSpace", [Qt.Key_Space]: "space",
        [Qt.Key_Left]: "Left", [Qt.Key_Right]: "Right", [Qt.Key_Up]: "Up", [Qt.Key_Down]: "Down",
        [Qt.Key_Home]: "Home", [Qt.Key_End]: "End", [Qt.Key_PageUp]: "Page_Up", [Qt.Key_PageDown]: "Page_Down",
        [Qt.Key_Insert]: "Insert", [Qt.Key_Delete]: "Delete",
        [Qt.Key_Comma]: "comma", [Qt.Key_Period]: "period", [Qt.Key_Slash]: "slash",
        [Qt.Key_Backslash]: "backslash", [Qt.Key_Semicolon]: "semicolon", [Qt.Key_Apostrophe]: "apostrophe",
        [Qt.Key_BracketLeft]: "bracketleft", [Qt.Key_BracketRight]: "bracketright",
        [Qt.Key_Minus]: "minus", [Qt.Key_Equal]: "equal", [Qt.Key_QuoteLeft]: "grave"
      })
      name = names[key] || ""
    }
    if (name === "") return ""
    var modifiers = []
    if (event.modifiers & Qt.ControlModifier) modifiers.push("ctrl")
    if (event.modifiers & Qt.AltModifier) modifiers.push("alt")
    if (event.modifiers & Qt.ShiftModifier) modifiers.push("shift")
    if (event.modifiers & Qt.MetaModifier) modifiers.push("logo")
    modifiers.push(name)
    return modifiers.join("+")
  }

  function modifierName(key) {
    if (key === Qt.Key_Control) return "ctrl"
    if (key === Qt.Key_Shift) return "shift"
    if (key === Qt.Key_Alt || key === Qt.Key_AltGr) return "alt"
    if (key === Qt.Key_Meta || key === Qt.Key_Super_L || key === Qt.Key_Super_R) return "logo"
    return ""
  }

  function displayKey(value) {
    var labels = ({ ctrl: "Ctrl", shift: "Shift", alt: "Alt", logo: "Super" })
    var parts = String(value || "").split("+")
    for (var i = 0; i < parts.length; i++) parts[i] = labels[parts[i]] || parts[i]
    return parts.join(" + ")
  }

  function applyMapperState(text) {
    var state = String(text || "").trim()
    // Atomic status updates should never expose an empty file, but ignoring
    // unknown content also prevents a transient read error from flipping UI.
    if (state !== "enabled" && state !== "disabled") return
    var enabled = state === "enabled"
    if (stateInitialized && enabled !== mappingEnabled) {
      Quickshell.execDetached([
        "omarchy-notification-send", "--app-name", "Controller Companion", "-g", "",
        enabled ? "Controller mapping enabled" : "Controller mapping disabled",
        enabled ? "Start + Back disables it" : "Press Start + Back to enable it again"
      ])
    }
    mappingEnabled = enabled
    stateInitialized = true
  }

  function refreshConfig() {
    configProc.running = false
    configProc.running = true
    appsProc.running = false
    appsProc.running = true
  }

  function toggleMapping() { Quickshell.execDetached([backend, "toggle"]) }

  function saveMapping(control, kind, value) {
    var next = []
    for (var i = 0; i < mappings.length; i++) {
      var row = mappings[i]
      next.push(row.id === control ? { id: row.id, type: kind, value: value } : row)
    }
    mappings = next
    Quickshell.execDetached([backend, "set", control, kind, value])
  }

  function saveSettings() {
    Quickshell.execDetached([backend, "settings", String(mouseSpeed), String(scrollSpeed)])
  }

  onOpenedChanged: if (opened) refreshConfig()

  FileView {
    id: stateFile
    path: root.statePath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.applyMapperState(text())
    onLoadFailed: root.applyMapperState("disabled")
  }

  Process {
    id: configProc
    command: [root.backend, "get"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var data = JSON.parse(String(text || "{}"))
          root.mouseSpeed = Number(data.mouseSpeed || 25)
          root.scrollSpeed = Number(data.scrollSpeed || 10)
          var rows = []
          var order = ["a", "b", "x", "y", "guide", "back", "start", "left_stick", "right_stick", "left_shoulder", "right_shoulder", "dpad_up", "dpad_right", "dpad_down", "dpad_left", "left_trigger", "right_trigger"]
          for (var i = 0; i < order.length; i++) {
            var id = order[i]
            var mapping = data.mappings[id] || { type: "disabled", value: "" }
            rows.push({ id: id, type: String(mapping.type), value: String(mapping.value || "") })
          }
          root.mappings = rows
        } catch (e) {}
      }
    }
  }

  Process {
    id: appsProc
    command: [root.backend, "apps"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try { root.appOptions = JSON.parse(String(text || "[]")) }
        catch (e) { root.appOptions = [] }
      }
    }
  }

  Timer {
    interval: 1200
    running: true
    repeat: false
    onTriggered: { stateFile.reload(); root.refreshConfig() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(620))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight, Style.space(760))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        id: scrollView
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: contentColumn
          // Keep focus/overlay borders away from the Flickable's clip edge.
          x: Style.space(4)
          width: Math.max(1, scrollView.width - Style.space(8))
          spacing: Style.space(14)

          Row {
            width: parent.width
            spacing: Style.space(12)
            Text {
              text: ""
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.display
              anchors.verticalCenter: parent.verticalCenter
            }
            Column {
              width: parent.width - Style.space(130)
              spacing: Style.space(2)
              Text {
                text: "Controller Companion"
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
              }
              Text {
                text: root.mappingEnabled ? "Enabled · Start + Back toggles" : "Disabled · Start + Back re-enables"
                color: Qt.darker(root.bar.foreground, 1.35)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
              }
            }
            Button {
              text: root.mappingEnabled ? "Disable" : "Enable"
              selected: root.mappingEnabled
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              anchors.verticalCenter: parent.verticalCenter
              onClicked: root.toggleMapping()
            }
          }

          PanelSeparator { foreground: root.bar.foreground }
          PanelSectionHeader { text: "POINTER"; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily }

          Column {
            width: parent.width
            spacing: Style.space(7)
            Item {
              width: parent.width
              implicitHeight: Math.max(mouseSpeedLabel.implicitHeight, mouseSpeedValue.implicitHeight)
              Text { id: mouseSpeedLabel; text: "Mouse speed"; color: root.bar.foreground; font.family: root.bar.fontFamily; font.pixelSize: Style.font.body; anchors.left: parent.left }
              Text { id: mouseSpeedValue; text: root.mouseSpeed + "%"; color: Qt.darker(root.bar.foreground, 1.35); font.family: root.bar.fontFamily; font.pixelSize: Style.font.caption; anchors.right: parent.right }
            }
            PanelSlider {
              width: parent.width
              bar: root.bar
              minimum: 1; maximum: 100; step: 1; integer: true
              value: root.mouseSpeed
              onMoved: function(v) { root.mouseSpeed = Math.round(v) }
              onReleased: function(v) { root.mouseSpeed = Math.round(v); root.saveSettings() }
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(7)
            Item {
              width: parent.width
              implicitHeight: Math.max(scrollSpeedLabel.implicitHeight, scrollSpeedValue.implicitHeight)
              Text { id: scrollSpeedLabel; text: "Scroll speed"; color: root.bar.foreground; font.family: root.bar.fontFamily; font.pixelSize: Style.font.body; anchors.left: parent.left }
              Text { id: scrollSpeedValue; text: root.scrollSpeed + "%"; color: Qt.darker(root.bar.foreground, 1.35); font.family: root.bar.fontFamily; font.pixelSize: Style.font.caption; anchors.right: parent.right }
            }
            PanelSlider {
              width: parent.width
              bar: root.bar
              minimum: 1; maximum: 100; step: 1; integer: true
              value: root.scrollSpeed
              onMoved: function(v) { root.scrollSpeed = Math.round(v) }
              onReleased: function(v) { root.scrollSpeed = Math.round(v); root.saveSettings() }
            }
          }

          PanelSeparator { foreground: root.bar.foreground }
          PanelSectionHeader { text: "BUTTONS"; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily }
          Text {
            width: parent.width
            text: "Changes apply immediately. Key mappings listen for the next key or chord; app lists are searchable."
            wrapMode: Text.WordWrap
            color: Qt.darker(root.bar.foreground, 1.4)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }

          Repeater {
            model: root.mappings
            delegate: Column {
              required property var modelData
              width: contentColumn.width
              spacing: Style.space(6)
              Text {
                text: root.controlLabels[modelData.id]
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
              }
              Row {
                id: mappingRow
                width: parent.width
                spacing: Style.space(8)
                Dropdown {
                  id: mappingType
                  width: parent.width * 0.31
                  showLabel: false
                  value: modelData.type
                  options: root.typeOptions
                  foreground: root.bar.foreground
                  fontFamily: root.bar.fontFamily
                  onChanged: function(v) {
                    var initial = ""
                    if (v === "key") root.captureControl = modelData.id
                    else if (v === "mouse") initial = "left"
                    else if (v === "omarchy") initial = "menu"
                    else if (v === "app" && root.appOptions.length > 0) initial = root.appOptions[0].value
                    root.saveMapping(modelData.id, v, initial)
                  }
                }

                Item {
                  id: mappingEditor
                  width: parent.width - mappingType.width - clearButton.width - parent.spacing * 2
                  height: Style.spacing.controlHeight

                  Item {
                    id: keyCapture
                    property bool listening: false
                    property string pendingModifier: ""
                    anchors.fill: parent
                    visible: modelData.type === "key"
                    function beginCapture() {
                      pendingModifier = ""
                      listening = true
                      forceActiveFocus()
                    }

                    Button {
                      anchors.fill: parent
                      text: keyCapture.listening ? "Press a key…" : (root.displayKey(modelData.value) || "Press a key…")
                      iconText: keyCapture.listening ? "󰌌" : ""
                      bordered: true
                      focusable: false
                      foreground: root.bar.foreground
                      fontFamily: root.bar.fontFamily
                      onClicked: keyCapture.beginCapture()
                    }

                    onActiveFocusChanged: {
                      if (!activeFocus && listening) {
                        listening = false
                        pendingModifier = ""
                      }
                    }
                    Keys.priority: Keys.BeforeItem
                    Keys.onPressed: function(event) {
                      if (!listening) return
                      var modifier = root.modifierName(event.key)
                      if (modifier !== "") {
                        if (pendingModifier === "") pendingModifier = modifier
                        event.accepted = true
                        return
                      }
                      var captured = root.keyName(event)
                      if (captured === "") return
                      listening = false
                      pendingModifier = ""
                      root.captureControl = ""
                      root.saveMapping(modelData.id, "key", captured)
                      event.accepted = true
                    }
                    Keys.onReleased: function(event) {
                      if (!listening || pendingModifier === "") return
                      var modifier = root.modifierName(event.key)
                      if (modifier !== pendingModifier) return
                      var captured = pendingModifier
                      listening = false
                      pendingModifier = ""
                      root.captureControl = ""
                      root.saveMapping(modelData.id, "key", captured)
                      event.accepted = true
                    }
                    Component.onCompleted: {
                      if (root.captureControl === modelData.id) Qt.callLater(beginCapture)
                    }
                  }

                  Dropdown {
                    anchors.fill: parent
                    visible: modelData.type === "mouse"
                    showLabel: false
                    value: modelData.value
                    options: root.mouseOptions
                  foreground: root.bar.foreground
                  fontFamily: root.bar.fontFamily
                  onChanged: function(v) {
                    if (visible && modelData.type === "mouse") root.saveMapping(modelData.id, "mouse", v)
                  }
                  }

                  Dropdown {
                    anchors.fill: parent
                    visible: modelData.type === "omarchy"
                    showLabel: false
                    value: modelData.value
                    options: root.omarchyOptions
                  foreground: root.bar.foreground
                  fontFamily: root.bar.fontFamily
                  onChanged: function(v) {
                    if (visible && modelData.type === "omarchy") root.saveMapping(modelData.id, "omarchy", v)
                  }
                  }

                  SearchableDropdown {
                    anchors.fill: parent
                    visible: modelData.type === "app"
                    showLabel: false
                    value: modelData.value
                    options: root.appOptions
                    placeholderText: "Search installed apps…"
                    emptyText: "No applications found"
                  foreground: root.bar.foreground
                  fontFamily: root.bar.fontFamily
                  onChanged: function(v) {
                    if (visible && modelData.type === "app") root.saveMapping(modelData.id, "app", v)
                  }
                  }

                  Text {
                    anchors.centerIn: parent
                    visible: modelData.type === "disabled"
                    text: "Not mapped"
                    color: Qt.darker(root.bar.foreground, 1.45)
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }

                PanelActionButton {
                  id: clearButton
                  anchors.verticalCenter: parent.verticalCenter
                  iconText: "󰅖"
                  tooltipText: "Clear mapping"
                  foreground: root.bar.foreground
                  fontFamily: root.bar.fontFamily
                  enabled: modelData.type !== "disabled" || modelData.value !== ""
                  onClicked: root.saveMapping(modelData.id, "disabled", "")
                }
              }
            }
          }
        }
      }
    }
  }
}
