# Omarchy Controller Companion

Turn an **8BitDo Ultimate 2C Wireless Controller** into a living-room mouse,
keyboard, and Omarchy remote. The status-bar controller icon opens a native
Omarchy panel for pointer tuning and per-button mappings.

## Features

- Left stick controls the pointer; right stick scrolls.
- Adjustable linear pointer and scroll speed. The panel's 1–100% range maps
  directly onto the engine's established 1–50 speed range.
- Map buttons to a keyboard key or chord, an Omarchy action, an installed app,
  a mouse button, or Disabled.
- Captures Return, keypad Enter, Space, and standalone modifiers correctly.
- Modifier mappings remain logically held for controller chords. For example,
  a button mapped to Super plus D-pad Left emits the real `Super+Left` chord.
- Back/View and Start/Menu can be mapped individually. Their actions run on
  release so pressing **Back + Start** can safely toggle the whole mapper.
- Native enabled/disabled notifications and a struck-through bar icon while
  disabled.
- The persistent virtual keyboard and mouse use Linux uinput, so compositor
  shortcuts, pointer motion, scrolling, and clicks need no helper application.

The controller's Mapping/Square and Star buttons configure hardware features
inside the controller and do not emit Linux input events, so they cannot be
remapped by this plugin.

## Requirements

- Omarchy with the current shell plugin commands
- 8BitDo Ultimate 2C Wireless Controller
- Python 3 and the normal `/dev/input` and `/dev/uinput` permissions provided
  by an Omarchy desktop session

There are no additional packages to install. The input engine uses Python's
standard library and Linux evdev/uinput directly.

## Install

Add and enable the plugin directly from GitHub:

```bash
omarchy plugin add https://github.com/myagoo/omarchy-controller-companion.git --enable
```

The plugin includes a native service entry point. Enabling it starts the
controller helper automatically; no Hyprland autostart edit, logout, or shell
restart is required.

Open the controller icon in the bar to change mappings. Changes take effect
immediately.

## Defaults

| Control | Default action |
| --- | --- |
| Left stick | Pointer |
| Right stick | Scroll |
| A / B | Left click / right click |
| X / Y | Tab / Space |
| Guide | Omarchy menu |
| Left / right stick click | Apps / Keybindings |
| Left / right shoulder | Previous / next workspace |
| D-pad | Arrow keys |
| Triggers | Disabled |
| Back / Start | Disabled individually; together toggle the mapper |

## Update

```bash
omarchy plugin update io.github.myagoo.controller-companion
```

User mappings live in
`~/.config/omarchy/controller-companion/controller-mappings.json`, outside the
git checkout, and are preserved across updates.

## Remove

```bash
omarchy plugin remove io.github.myagoo.controller-companion
```

Removal stops the helper. It intentionally preserves your mapping file. To
also remove that saved configuration:

```bash
rm -r ~/.config/omarchy/controller-companion
```

## Troubleshooting

- If the icon says Disabled, press Back + Start or right-click the icon.
- If the controller is not detected, verify its name with
  `cat /proc/bus/input/devices` and confirm it is the Ultimate 2C Wireless
  model.
- If an older release left AntiMicroX running, close that process once. Version
  1.1 and later neither starts nor communicates with AntiMicroX.
- Service errors appear in the Omarchy Shell journal. Inspect them with
  `journalctl --user -u omarchy-shell`.

## Development

Validate the manifest and run the backend tests:

```bash
omarchy plugin validate .
python -m unittest discover -s tests -v
```

The project uses only Python's standard library at runtime. Its persistent
uinput keyboard emits complete key chords into Hyprland, while a separate
uinput pointer handles linear analog movement, scrolling, and mouse buttons.
Captured keysyms are resolved against Hyprland's active keyboard layout, so
semantic mappings remain correct on layouts such as AZERTY.

The persistent-uinput approach was inspired by Parminder Klair's MIT-licensed
[Controller Control](https://github.com/perminder-klair/omarchy-controller-control).

## License

[MIT](LICENSE)
