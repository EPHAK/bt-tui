"""
PipeWire/PulseAudio-compat helpers for Bluetooth audio codec inspection and
profile (codec) switching.

Everything here shells out to `pactl` and `pw-dump`, both confirmed against
the real running system (pactl 17.0 supports `-f json`; pw-dump emits a flat
list of PipeWire objects with `type`/`info`/`props`). Nothing here is a
guess at a schema -- see bt-tui's build notes for the exact commands used
to verify each field before this was written.

Real, confirmed property/profile facts this module relies on:
  - `api.bluez5.codec` on a PipeWire node is the active A2DP codec name
    (e.g. "sbc", "sbc_xq", "aac", "aptx", "aptx_hd", "ldac", "lc3").
  - `pactl -f json list cards` gives each card's `active_profile` and a
    `profiles` dict of {profile_name: {description, available, ...}}.
    For a connected bluez5 device, each supported codec shows up as its
    own selectable profile (this is how codec switching is actually
    exposed -- there is no separate "set codec" call, you switch profile).
  - LDAC has an additional quality knob (`bluez5.a2dp.ldac.quality`:
    auto/hq/sq/mq) that is a WirePlumber *config* setting, not something
    switchable per-connection at runtime -- documented here as a real
    limitation rather than papered over.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field


@dataclass
class BluezAudioNode:
    node_id: int
    node_name: str
    media_class: str
    codec: str | None = None
    sample_rate: str | None = None
    channels: str | None = None


@dataclass
class CardProfile:
    name: str
    description: str
    available: bool


@dataclass
class Card:
    index: int
    name: str
    active_profile: str
    profiles: list[CardProfile] = field(default_factory=list)


def _run_json(cmd: list[str]) -> list | dict:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def list_bluez_audio_nodes() -> list[BluezAudioNode]:
    """Find PipeWire audio nodes backed by a bluez5 device, with live codec info."""
    objects = _run_json(["pw-dump"])
    nodes = []
    for obj in objects:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        props = obj.get("info", {}).get("props", {})
        media_class = props.get("media.class", "")
        if props.get("device.api") != "bluez5" or "Audio" not in media_class:
            continue
        nodes.append(
            BluezAudioNode(
                node_id=obj["id"],
                node_name=props.get("node.name", ""),
                media_class=media_class,
                codec=props.get("api.bluez5.codec"),
                sample_rate=props.get("audio.rate"),
                channels=props.get("audio.channels"),
            )
        )
    return nodes


def list_cards() -> list[Card]:
    data = _run_json(["pactl", "-f", "json", "list", "cards"])
    cards = []
    for c in data:
        profiles = [
            CardProfile(name=name, description=p.get("description", name), available=p.get("available", False))
            for name, p in c.get("profiles", {}).items()
        ]
        cards.append(Card(index=c["index"], name=c["name"], active_profile=c.get("active_profile", ""), profiles=profiles))
    return cards


def find_bluez_card(device_address: str) -> Card | None:
    """
    Bluez cards are named like bluez_card.XX_XX_XX_XX_XX_XX -- match on the
    address with ':' replaced by '_', which is BlueZ/PipeWire's own naming
    convention for these object/card names.
    """
    addr_key = device_address.replace(":", "_")
    for card in list_cards():
        if card.name.startswith("bluez_card.") and addr_key in card.name:
            return card
    return None


def set_card_profile(card_name: str, profile_name: str) -> None:
    result = subprocess.run(
        ["pactl", "set-card-profile", card_name, profile_name],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"set-card-profile failed: {result.stderr.strip()}")


def codec_from_profile_name(profile_name: str) -> str | None:
    """
    Bluez A2DP profile names embed the codec, e.g. 'a2dp-sink-sbc_xq',
    'a2dp-sink-aac', 'headset-head-unit-cvsd'. Extract the trailing codec
    token if present -- purely a display helper, not used for switching
    (switching uses the full profile name as-is).
    """
    if "a2dp-sink-" in profile_name:
        return profile_name.split("a2dp-sink-", 1)[1]
    if "a2dp-source-" in profile_name:
        return profile_name.split("a2dp-source-", 1)[1]
    return None
