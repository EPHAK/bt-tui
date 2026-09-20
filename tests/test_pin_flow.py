import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bt_tui.app import BtTuiApp


async def main():
    app = BtTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Simulate exactly how PairingAgent invokes this: as a bare coroutine
        # call from outside any Textual action/worker context (dbus_next's
        # own asyncio task, not ours).
        async def simulate_agent_call():
            result = await app.ask_pin("/org/bluez/hci0/dev_XX", mode="pin")
            print("ask_pin returned:", repr(result))

        task = asyncio.ensure_future(simulate_agent_call())
        await pilot.pause(0.3)
        print("screen stack while pin modal open:", [type(s).__name__ for s in app.screen_stack])

        await pilot.press("1", "2", "3", "4")
        await pilot.press("enter")
        await pilot.pause(0.3)
        await task
        print("screen stack after dismiss:", [type(s).__name__ for s in app.screen_stack])

        # Now the confirm flow
        async def simulate_confirm_call():
            result = await app.ask_confirm("/org/bluez/hci0/dev_XX", 654321)
            print("ask_confirm returned:", result)

        task2 = asyncio.ensure_future(simulate_confirm_call())
        await pilot.pause(0.3)
        await pilot.press("tab")  # move focus to No or Yes button
        await pilot.press("enter")
        await pilot.pause(0.3)
        await task2


asyncio.run(main())
