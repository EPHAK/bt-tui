# bt-tui

A terminal Bluetooth manager. Scan, pair, connect, and inspect devices
with arrow keys, without leaving the terminal.

## Features

- Live device scanning with real-time updates as devices are discovered
- Pair, connect, disconnect, trust, and remove devices
- Full pairing agent: PIN-code entry and passkey confirmation for
  devices that require them
- Device detail view: address, RSSI, battery percentage, device class,
  advertised services
- Bluetooth audio codec inspection and switching (SBC / SBC-XQ / AAC /
  aptX / etc.) via PipeWire card profiles
- Headless CLI mode for scripting, no TUI required

## Usage

```bash
bt-tui                          # interactive TUI
bt-tui --list                   # scan and list devices, then exit
bt-tui --connect <name-or-mac>  # pair (if needed) and connect
bt-tui --disconnect <name-or-mac>
```

Device names may be partial and case-insensitive (`bt-tui --connect
pixel` matches "Pixel Buds Pro"). A full MAC address always matches
exactly.

### Keybindings

| Key | Action |
|---|---|
| `↑` / `↓` | Move selection |
| `Enter` | Open device details |
| `s` | Toggle scanning |
| `p` | Pair selected device |
| `c` | Connect selected device |
| `d` | Disconnect selected device |
| `r` | Refresh device list |
| `q` | Quit |

Inside the device detail screen:

| Key | Action |
|---|---|
| `↑` / `↓` + `Enter` | Switch audio codec/profile |
| `t` | Toggle trusted |
| `d` | Disconnect |
| `r` | Remove/forget device |
| `Esc` | Back |

## Requirements

- Linux with BlueZ (`bluetoothd`) and PipeWire
- Python 3.10+
- `python-textual`, `python-dbus-next`

```bash
pip install textual dbus-next
```

## Installation

```bash
git clone https://github.com/EPHAK/bt-tui.git
ln -s "$(pwd)/bt-tui/bt-tui" ~/.local/bin/bt-tui
```

Ensure `~/.local/bin` is on your `PATH`.

## How it works

`bt-tui` talks directly to BlueZ over D-Bus (`org.bluez.Adapter1`,
`Device1`, `AgentManager1`) using `dbus-next`, and to PipeWire via
`pactl`/`pw-dump` for audio codec and card-profile information. There
is no daemon and no persistent state beyond what BlueZ and PipeWire
already track.

## License

MIT
