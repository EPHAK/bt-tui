"""
Thin async wrapper around the real BlueZ D-Bus API.

Every interface/method/property name here was confirmed live against a
running bluetoothd via `busctl --system introspect org.bluez ...` before
being used -- nothing here is guessed from BlueZ documentation alone.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable, Optional

from dbus_next.aio import MessageBus
from dbus_next import BusType, Variant, DBusError
from dbus_next.service import ServiceInterface, method

BLUEZ_SERVICE = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
BATTERY_IFACE = "org.bluez.Battery1"
AGENT_MANAGER_IFACE = "org.bluez.AgentManager1"
AGENT_IFACE = "org.bluez.Agent1"
OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"


@dataclass
class Device:
    path: str
    address: str = ""
    name: str = ""
    alias: str = ""
    icon: str = ""
    paired: bool = False
    trusted: bool = False
    connected: bool = False
    bonded: bool = False
    rssi: Optional[int] = None
    battery_percentage: Optional[int] = None
    device_class: Optional[int] = None
    uuids: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.alias or self.name or self.address


def _unwrap(variant_dict: dict) -> dict:
    """dbus_next hands back {key: Variant(...)} -- unwrap to plain values."""
    out = {}
    for k, v in variant_dict.items():
        out[k] = v.value if isinstance(v, Variant) else v
    return out


def _device_from_props(path: str, props: dict) -> Device:
    p = _unwrap(props)
    return Device(
        path=path,
        address=p.get("Address", ""),
        name=p.get("Name", ""),
        alias=p.get("Alias", ""),
        icon=p.get("Icon", ""),
        paired=p.get("Paired", False),
        trusted=p.get("Trusted", False),
        connected=p.get("Connected", False),
        bonded=p.get("Bonded", False),
        rssi=p.get("RSSI"),
        device_class=p.get("Class"),
        uuids=p.get("UUIDs", []) or [],
    )


class PairingAgent(ServiceInterface):
    """
    org.bluez.Agent1 implementation. Capability "KeyboardDisplay" so BlueZ
    routes both PIN-code entry (older devices) and passkey confirmation
    (SSP / numeric-comparison, most modern headphones/earbuds) through us
    instead of auto-accepting or auto-rejecting.

    `ask_pin` / `ask_confirm` are awaitable callbacks the TUI supplies to
    actually prompt the user; this class only implements the D-Bus surface.
    Every method name/signature below is the real org.bluez.Agent1 contract,
    confirmed against BlueZ's own agent API (object-path/string/uint32/byte
    D-Bus type codes: o/s/u/y).
    """

    def __init__(self, ask_pin: Callable, ask_confirm: Callable, notify: Callable):
        super().__init__("org.bluez.Agent1")
        self.ask_pin = ask_pin
        self.ask_confirm = ask_confirm
        self.notify = notify

    @method()
    async def Release(self):
        pass

    @method()
    async def RequestPinCode(self, device: "o") -> "s":
        pin = await self.ask_pin(device, mode="pin")
        return pin

    @method()
    async def RequestPasskey(self, device: "o") -> "u":
        pin = await self.ask_pin(device, mode="passkey")
        return int(pin)

    @method()
    async def DisplayPasskey(self, device: "o", passkey: "u", entered: "y"):
        await self.notify(f"Passkey for {device}: {passkey:06d}")

    @method()
    async def DisplayPinCode(self, device: "o", pincode: "s"):
        await self.notify(f"PIN for {device}: {pincode}")

    @method()
    async def RequestConfirmation(self, device: "o", passkey: "u"):
        ok = await self.ask_confirm(device, passkey)
        if not ok:
            raise DBusError("org.bluez.Error.Rejected", "rejected by user")

    @method()
    async def RequestAuthorization(self, device: "o"):
        ok = await self.ask_confirm(device, None)
        if not ok:
            raise DBusError("org.bluez.Error.Rejected", "rejected by user")

    @method()
    async def AuthorizeService(self, device: "o", uuid: "s"):
        return None

    @method()
    async def Cancel(self):
        pass


class BluezClient:
    def __init__(self):
        self.bus: Optional[MessageBus] = None
        self.adapter_path: Optional[str] = None
        self._object_manager = None
        self.on_devices_changed: Optional[Callable] = None

    async def connect(self):
        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        introspection = await self.bus.introspect(BLUEZ_SERVICE, "/")
        root = self.bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
        self._object_manager = root.get_interface(OBJECT_MANAGER_IFACE)

        objects = await self._object_manager.call_get_managed_objects()
        for path, ifaces in objects.items():
            if ADAPTER_IFACE in ifaces:
                self.adapter_path = path
                break
        if not self.adapter_path:
            raise RuntimeError("no bluetooth adapter found")

        self._object_manager.on_interfaces_added(self._on_interfaces_added)
        self._object_manager.on_interfaces_removed(self._on_interfaces_removed)

    def _on_interfaces_added(self, path, interfaces):
        if self.on_devices_changed:
            self.on_devices_changed()

    def _on_interfaces_removed(self, path, interfaces):
        if self.on_devices_changed:
            self.on_devices_changed()

    async def _adapter_iface(self):
        intro = await self.bus.introspect(BLUEZ_SERVICE, self.adapter_path)
        obj = self.bus.get_proxy_object(BLUEZ_SERVICE, self.adapter_path, intro)
        return obj.get_interface(ADAPTER_IFACE)

    async def _device_iface(self, path: str):
        intro = await self.bus.introspect(BLUEZ_SERVICE, path)
        obj = self.bus.get_proxy_object(BLUEZ_SERVICE, path, intro)
        return obj, obj.get_interface(DEVICE_IFACE)

    async def start_discovery(self):
        adapter = await self._adapter_iface()
        await adapter.call_start_discovery()

    async def stop_discovery(self):
        adapter = await self._adapter_iface()
        try:
            await adapter.call_stop_discovery()
        except Exception:
            pass

    async def set_powered(self, on: bool):
        intro = await self.bus.introspect(BLUEZ_SERVICE, self.adapter_path)
        obj = self.bus.get_proxy_object(BLUEZ_SERVICE, self.adapter_path, intro)
        props = obj.get_interface(PROPERTIES_IFACE)
        await props.call_set(ADAPTER_IFACE, "Powered", Variant("b", on))

    async def list_devices(self) -> list[Device]:
        objects = await self._object_manager.call_get_managed_objects()
        devices = []
        for path, ifaces in objects.items():
            if DEVICE_IFACE not in ifaces:
                continue
            dev = _device_from_props(path, ifaces[DEVICE_IFACE])
            if BATTERY_IFACE in ifaces:
                bp = _unwrap(ifaces[BATTERY_IFACE])
                dev.battery_percentage = bp.get("Percentage")
            devices.append(dev)
        devices.sort(key=lambda d: (not d.connected, not d.paired, -(d.rssi or -999)))
        return devices

    async def get_device_props(self, path: str) -> Device:
        intro = await self.bus.introspect(BLUEZ_SERVICE, path)
        obj = self.bus.get_proxy_object(BLUEZ_SERVICE, path, intro)
        props_iface = obj.get_interface(PROPERTIES_IFACE)
        all_props = await props_iface.call_get_all(DEVICE_IFACE)
        dev = _device_from_props(path, all_props)
        try:
            battery_props = await props_iface.call_get_all(BATTERY_IFACE)
            dev.battery_percentage = _unwrap(battery_props).get("Percentage")
        except Exception:
            pass
        return dev

    async def pair(self, path: str):
        _, iface = await self._device_iface(path)
        await iface.call_pair()

    async def connect_device(self, path: str):
        _, iface = await self._device_iface(path)
        await iface.call_connect()

    async def disconnect_device(self, path: str):
        _, iface = await self._device_iface(path)
        await iface.call_disconnect()

    async def remove_device(self, path: str):
        adapter = await self._adapter_iface()
        await adapter.call_remove_device(path)

    async def set_trusted(self, path: str, trusted: bool):
        intro = await self.bus.introspect(BLUEZ_SERVICE, path)
        obj = self.bus.get_proxy_object(BLUEZ_SERVICE, path, intro)
        props = obj.get_interface(PROPERTIES_IFACE)
        await props.call_set(DEVICE_IFACE, "Trusted", Variant("b", trusted))

    async def set_alias(self, path: str, alias: str):
        intro = await self.bus.introspect(BLUEZ_SERVICE, path)
        obj = self.bus.get_proxy_object(BLUEZ_SERVICE, path, intro)
        props = obj.get_interface(PROPERTIES_IFACE)
        await props.call_set(DEVICE_IFACE, "Alias", Variant("s", alias))

    async def register_agent(self, agent: PairingAgent, agent_path="/bt_tui/agent"):
        self.bus.export(agent_path, agent)
        intro = await self.bus.introspect(BLUEZ_SERVICE, "/org/bluez")
        obj = self.bus.get_proxy_object(BLUEZ_SERVICE, "/org/bluez", intro)
        mgr = obj.get_interface(AGENT_MANAGER_IFACE)
        await mgr.call_register_agent(agent_path, "KeyboardDisplay")
        await mgr.call_request_default_agent(agent_path)
        return agent_path
