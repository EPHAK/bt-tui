import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bt_tui.app import BtTuiApp


async def main():
    app = BtTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one("DataTable")
        print("rows after mount:", table.row_count)
        for path, d in zip([d.path for d in app.devices], app.devices):
            print(" ", d.address, d.display_name, "connected=", d.connected)

        # navigate down and open details on first device
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        print("screen stack:", [type(s).__name__ for s in app.screen_stack])
        await pilot.press("escape")
        await pilot.pause()
        print("screen stack after escape:", [type(s).__name__ for s in app.screen_stack])


asyncio.run(main())
