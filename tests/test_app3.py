import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bt_tui.app import BtTuiApp, DeviceDetailScreen
from textual.widgets import Static, ListView


async def main():
    app = BtTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause(0.3)
        screen = app.screen
        assert isinstance(screen, DeviceDetailScreen), type(screen)
        info = screen.query_one("#detail-info", Static)
        codec_status = screen.query_one("#codec-status", Static)
        profile_list = screen.query_one("#profile-list", ListView)
        print("info content:", info.content)
        print("codec status content:", codec_status.content)
        print("profile list item count:", len(profile_list.children))
        for item in profile_list.children:
            print("  item:", item)


asyncio.run(main())
