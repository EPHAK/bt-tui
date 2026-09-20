from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, DataTable, Static, Input, Button, Label, ListView, ListItem

from .bluez import BluezClient, PairingAgent, Device
from . import pipewire


class PinModal(ModalScreen[str | None]):
    """Prompts for a PIN/passkey. Enter submits, Escape cancels (=reject)."""

    def __init__(self, device_path: str, mode: str):
        super().__init__()
        self.device_path = device_path
        self.mode = mode

    def compose(self) -> ComposeResult:
        label = "Enter PIN code:" if self.mode == "pin" else "Enter passkey (numbers):"
        with Vertical(id="pin-box"):
            yield Label(f"Pairing with {self.device_path}")
            yield Label(label)
            yield Input(id="pin-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """Yes/No confirmation, e.g. numeric-comparison passkey confirmation."""

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self.message)
            with Horizontal():
                yield Button("Yes", id="yes", variant="success")
                yield Button("No", id="no", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(False)


class MessageModal(ModalScreen[None]):
    """One-line informational popup, e.g. BlueZ asking us to *display* a passkey."""

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="msg-box"):
            yield Label(self.message)
            yield Label("(press any key)")

    def on_key(self, event) -> None:
        self.dismiss(None)


class DeviceDetailScreen(ModalScreen[None]):
    """Device info + codec/profile panel for the selected device."""

    BINDINGS = [
        Binding("escape", "dismiss_screen", "Back"),
        Binding("t", "toggle_trust", "Toggle trust"),
        Binding("d", "disconnect", "Disconnect"),
        Binding("r", "remove", "Remove/forget"),
    ]

    def __init__(self, app_ref: "BtTuiApp", device: Device):
        super().__init__()
        self.app_ref = app_ref
        self.device = device

    def compose(self) -> ComposeResult:
        d = self.device
        with Vertical(id="detail-box"):
            yield Static(f"[b]{d.display_name}[/b]", id="detail-title")
            yield Static(
                f"Address: {d.address}\n"
                f"Paired: {d.paired}   Trusted: {d.trusted}   Connected: {d.connected}\n"
                f"RSSI: {d.rssi if d.rssi is not None else 'n/a'}   "
                f"Battery: {d.battery_percentage if d.battery_percentage is not None else 'n/a'}%\n"
                f"Class: {d.device_class}\n"
                f"Icon: {d.icon}\n"
                f"UUIDs: {len(d.uuids)} service(s)",
                id="detail-info",
            )
            yield Static("Codec / Profile", id="codec-title")
            yield ListView(id="profile-list")
            yield Static("", id="codec-status")
            yield Static("[t] toggle trust  [d] disconnect  [r] remove  [esc] back", id="detail-hints")

    async def on_mount(self) -> None:
        await self.refresh_codec_panel()

    async def refresh_codec_panel(self) -> None:
        codec_status = self.query_one("#codec-status", Static)
        profile_list = self.query_one("#profile-list", ListView)
        await profile_list.clear()
        self.card_name = None

        try:
            nodes = pipewire.list_bluez_audio_nodes()
        except Exception as e:
            codec_status.update(f"[red]could not read PipeWire state: {e}[/red]")
            return

        matching = [n for n in nodes if self.device.address.replace(":", "_") in n.node_name]
        if matching:
            n = matching[0]
            codec_status.update(
                f"Active codec: [b]{n.codec or 'unknown'}[/b]   "
                f"Rate: {n.sample_rate or '?'}   Channels: {n.channels or '?'}"
            )
        else:
            codec_status.update("[dim]not currently an active audio node (connect audio first)[/dim]")

        card = pipewire.find_bluez_card(self.device.address)
        if not card:
            await profile_list.append(ListItem(Label("[dim]no PipeWire card for this device yet[/dim]")))
            return
        self.card_name = card.name
        active_index = 0
        for i, p in enumerate(card.profiles):
            if p.name == "off":
                continue
            marker = "* " if p.name == card.active_profile else "  "
            if p.name == card.active_profile:
                active_index = len(profile_list.children)
            label = f"{marker}{p.description}" + ("" if p.available else "  [dim](unavailable)[/dim]")
            item = ListItem(Label(label))
            item.profile_name = p.name
            item.available = p.available
            await profile_list.append(item)

        # ListView.index stays None after programmatically appending items --
        # confirmed live: without this, arrow keys/enter on the list had no
        # effect at all, since there was never an initial highlighted item
        # for them to act on. Default to the currently active profile.
        if len(profile_list.children) > 0:
            profile_list.index = active_index

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        profile_name = getattr(item, "profile_name", None)
        if not profile_name or not getattr(item, "available", False) or not self.card_name:
            return
        try:
            pipewire.set_card_profile(self.card_name, profile_name)
            self.app_ref.notify(f"Switched profile to {profile_name}")
        except Exception as e:
            self.app_ref.notify(f"Failed to switch profile: {e}", severity="error")
        # PipeWire tears down and recreates the bluez5 node on a profile
        # switch -- confirmed live: refreshing immediately can catch the
        # gap and show "not an active audio node" even though the switch
        # itself succeeded. A short wait avoids that stale-looking read.
        await asyncio.sleep(0.6)
        await self.refresh_codec_panel()

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

    async def action_toggle_trust(self) -> None:
        await self.app_ref.client.set_trusted(self.device.path, not self.device.trusted)
        self.device = await self.app_ref.client.get_device_props(self.device.path)
        await self.recompose()

    async def action_disconnect(self) -> None:
        try:
            await self.app_ref.client.disconnect_device(self.device.path)
        except Exception as e:
            self.app_ref.notify(f"Disconnect failed: {e}", severity="error")
        self.dismiss(None)

    async def action_remove(self) -> None:
        try:
            await self.app_ref.client.remove_device(self.device.path)
        except Exception as e:
            self.app_ref.notify(f"Remove failed: {e}", severity="error")
        self.dismiss(None)


class BtTuiApp(App):
    CSS = """
    #pin-box, #confirm-box, #msg-box, #detail-box {
        width: 60;
        height: auto;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #detail-box { width: 70; height: auto; }
    #profile-list { height: 8; border: solid $accent; }
    DeviceDetailScreen, PinModal, ConfirmModal, MessageModal {
        align: center middle;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "toggle_scan", "Scan"),
        Binding("p", "pair", "Pair"),
        Binding("c", "connect", "Connect"),
        Binding("d", "disconnect", "Disconnect"),
        Binding("r", "refresh", "Refresh"),
    ]
    # "enter" for details is handled via on_data_table_row_selected below,
    # not an app-level Binding: DataTable consumes the Enter keypress
    # itself to fire RowSelected before it would ever bubble up to an
    # App-level binding, confirmed by testing (a bound app-level "enter"
    # action never fired while the table had focus; calling the action
    # directly worked fine, isolating it to key-dispatch, not the logic).

    def __init__(self):
        super().__init__()
        self.client = BluezClient()
        self.devices: list[Device] = []
        self.scanning = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(id="device-table", cursor_type="row")
        yield Static("[dim]s: scan  p: pair  c: connect  d: disconnect  enter: details  r: refresh  q: quit[/dim]", id="hints")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Status", "Name", "Address", "RSSI")
        await self.client.connect()

        agent = PairingAgent(self.ask_pin, self.ask_confirm, self.show_message)
        await self.client.register_agent(agent)

        self.client.on_devices_changed = self.on_devices_changed
        await self.refresh_devices()
        self.set_interval(2.0, self.refresh_devices_task)

    def refresh_devices_task(self) -> None:
        self.run_worker(self.refresh_devices(), exclusive=True, group="refresh")

    def on_devices_changed(self) -> None:
        self.run_worker(self.refresh_devices(), exclusive=True, group="refresh")

    async def refresh_devices(self) -> None:
        self.devices = await self.client.list_devices()
        table = self.query_one(DataTable)
        table.clear()
        for d in self.devices:
            status = "🔗" if d.connected else ("✓" if d.paired else " ")
            table.add_row(status, d.display_name, d.address, str(d.rssi) if d.rssi is not None else "-", key=d.path)

    def _selected_device(self) -> Device | None:
        table = self.query_one(DataTable)
        if table.cursor_row is None or not self.devices:
            return None
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            path = row_key.value
        except Exception:
            return None
        for d in self.devices:
            if d.path == path:
                return d
        return None

    async def action_toggle_scan(self) -> None:
        if self.scanning:
            await self.client.stop_discovery()
            self.scanning = False
            self.notify("Scan stopped")
        else:
            await self.client.start_discovery()
            self.scanning = True
            self.notify("Scanning...")

    async def action_pair(self) -> None:
        d = self._selected_device()
        if not d:
            return
        try:
            await self.client.pair(d.path)
            self.notify(f"Paired with {d.display_name}")
        except Exception as e:
            self.notify(f"Pair failed: {e}", severity="error")
        await self.refresh_devices()

    async def action_connect(self) -> None:
        d = self._selected_device()
        if not d:
            return
        try:
            if not d.paired:
                await self.client.pair(d.path)
            await self.client.connect_device(d.path)
            self.notify(f"Connected to {d.display_name}")
        except Exception as e:
            self.notify(f"Connect failed: {e}", severity="error")
        await self.refresh_devices()

    async def action_disconnect(self) -> None:
        d = self._selected_device()
        if not d:
            return
        try:
            await self.client.disconnect_device(d.path)
        except Exception as e:
            self.notify(f"Disconnect failed: {e}", severity="error")
        await self.refresh_devices()

    async def action_show_detail(self) -> None:
        d = self._selected_device()
        if not d:
            return
        fresh = await self.client.get_device_props(d.path)
        await self.push_screen(DeviceDetailScreen(self, fresh))

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        await self.action_show_detail()

    async def action_refresh(self) -> None:
        await self.refresh_devices()

    # These three are invoked from PairingAgent's D-Bus method callbacks
    # (dbus_next's own asyncio task, not a Textual action/worker), so
    # push_screen_wait can't be called directly from them -- confirmed by
    # testing: it raises "NoActiveWorker" outside a worker context, the
    # exact same issue found and fixed in eqt's action methods, just
    # reached from a different kind of caller here. Fixed the same way,
    # via a worker, since these callers aren't already Textual actions
    # that `@work` could decorate directly.
    async def ask_pin(self, device_path: str, mode: str) -> str:
        worker = self.run_worker(self.push_screen_wait(PinModal(device_path, mode)))
        result = await worker.wait()
        return result or ""

    async def ask_confirm(self, device_path: str, passkey) -> bool:
        msg = f"Confirm pairing with {device_path}"
        if passkey is not None:
            msg += f"\nPasskey: {passkey:06d}"
        worker = self.run_worker(self.push_screen_wait(ConfirmModal(msg)))
        result = await worker.wait()
        return bool(result)

    async def show_message(self, message: str) -> None:
        worker = self.run_worker(self.push_screen_wait(MessageModal(message)))
        await worker.wait()


async def _headless_disconnect(address: str) -> int:
    client = BluezClient()
    await client.connect()
    devices = await client.list_devices()
    match = next((d for d in devices if d.address.lower() == address.lower()), None)
    if not match:
        print(f"no known device with address {address}")
        return 1
    try:
        await client.disconnect_device(match.path)
        print(f"disconnected {match.display_name} ({match.address})")
        return 0
    except Exception as e:
        print(f"disconnect failed: {e}")
        return 1


async def _headless_connect(address: str) -> int:
    client = BluezClient()
    await client.connect()
    devices = await client.list_devices()
    match = next((d for d in devices if d.address.lower() == address.lower()), None)
    if not match:
        print(f"no known device with address {address} (scan for it in the TUI first, or pair it)")
        return 1
    try:
        if not match.paired:
            await client.pair(match.path)
        await client.connect_device(match.path)
        print(f"connected {match.display_name} ({match.address})")
        return 0
    except Exception as e:
        print(f"connect failed: {e}")
        return 1


async def _headless_list() -> int:
    client = BluezClient()
    await client.connect()
    devices = await client.list_devices()
    for d in devices:
        status = "connected" if d.connected else ("paired" if d.paired else "known")
        print(f"{d.address}  {d.display_name!r}  [{status}]")
    return 0


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="bt-tui -- Bluetooth TUI (run with no arguments for the interactive UI)"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--disconnect", metavar="ADDRESS", help="disconnect a device by address, no TUI")
    group.add_argument("--connect", metavar="ADDRESS", help="pair (if needed) and connect a device by address, no TUI")
    group.add_argument("--list", action="store_true", help="list known devices and exit, no TUI")
    args = parser.parse_args()

    if args.disconnect:
        sys.exit(asyncio.run(_headless_disconnect(args.disconnect)))
    elif args.connect:
        sys.exit(asyncio.run(_headless_connect(args.connect)))
    elif args.list:
        sys.exit(asyncio.run(_headless_list()))
    else:
        BtTuiApp().run()


if __name__ == "__main__":
    main()
