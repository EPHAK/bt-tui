import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bt_tui.bluez import BluezClient, PairingAgent


async def ask_pin(device, mode):
    print(f"[agent] would ask for {mode} for {device}")
    return "0000"


async def ask_confirm(device, passkey):
    print(f"[agent] would confirm {device} passkey={passkey}")
    return True


async def notify(msg):
    print(f"[agent] notify: {msg}")


async def main():
    client = BluezClient()
    await client.connect()
    agent = PairingAgent(ask_pin, ask_confirm, notify)
    path = await client.register_agent(agent)
    print("agent registered at", path)
    await asyncio.sleep(1)


asyncio.run(main())
