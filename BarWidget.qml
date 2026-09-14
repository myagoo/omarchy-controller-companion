import QtQuick
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.myagoo.controller-companion"

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool mappingEnabled: panelLoader.item ? panelLoader.item.mappingEnabled === true : false
  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: { root.injectPanel(); Qt.callLater(root.injectPanel) }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    active: false
    dimmed: false
    iconComponent: Component {
      Item {
        Text {
          anchors.centerIn: parent
          text: ""
          color: button.foreground
          font.family: button.fontFamily
          font.pixelSize: button.fontSize
        }
        Rectangle {
          visible: !root.mappingEnabled
          anchors.centerIn: parent
          width: parent.width * 1.05
          height: Math.max(1.5, parent.height * 0.09)
          radius: height / 2
          rotation: -45
          color: button.foreground
        }
      }
    }
    slotSize: Style.bar.statusSlot
    tooltipText: root.mappingEnabled
      ? "Controller mapping enabled — click to configure, right-click to disable"
      : "Controller mapping disabled — click to configure, right-click to enable"
    onPressed: function(b) {
      if (b === Qt.RightButton && panelLoader.item) panelLoader.item.toggleMapping()
      else root.toggle()
    }
  }
}
