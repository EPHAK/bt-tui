import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bt_tui.bluez import BluezClient


async def main():
    client = BluezClient()
    await client.connect()
    print("adapter:", client.adapter_path)
    devices = await client.list_devices()
    print(f"found {len(devices)} known device(s):")
    for d in devices:
        print(f"  {d.address}  {d.display_name!r}  paired={d.paired} connected={d.connected} rssi={d.rssi}")

    print("starting discovery for 8s...")
    await client.start_discovery()
    await asyncio.sleep(8)
    devices = await client.list_devices()
    print(f"after discovery: {len(devices)} device(s):")
    for d in devices:
        print(f"  {d.address}  {d.display_name!r}  paired={d.paired} connected={d.connected} rssi={d.rssi}")
    await client.stop_discovery()


asyncio.run(main())
