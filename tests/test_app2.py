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
        print("focused widget:", app.focused)
        print("table cursor_row:", table.cursor_row)
        d = app._selected_device()
        print("selected device via helper:", d)

        # call the action directly to isolate binding-dispatch vs action logic
        await app.action_show_detail()
        await pilot.pause()
        print("screen stack after direct action call:", [type(s).__name__ for s in app.screen_stack])


asyncio.run(main())
