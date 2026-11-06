"""Exercise the close script with a pending dialog and changing window inventory."""

import asyncio
import json
import shutil
import subprocess
import unittest

from kirabridge.bridge_core.models import UncertainExecution
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport


@unittest.skipUnless(shutil.which("node"), "Node is needed to execute the native JS fixture")
class TerminalCloseConfirmation(unittest.IsolatedAsyncioTestCase):
    async def close(self, mode):
        transport = TerminalAppTransport(asyncio.Lock())
        transport.native_target = lambda pane: ""
        calls = []

        async def native(source, *, mutation=False):
            calls.append(mutation)
            setup = """
                const mode = MODE;
                let ids = mode === 'only' ? [101] : [101, 202];
                const app = {windows: () => ids.map(id => ({id: () => id}))};
                const targetWindow = {
                    id: () => 101,
                    close: () => {
                        if (mode === 'closed') ids = [202];
                        if (mode === 'foreign_removed') ids = [];
                    }
                };
                const delay = () => {};
            """.replace("MODE", json.dumps(mode))
            completed = await asyncio.to_thread(
                subprocess.run,
                ["node", "-e", "console.log(eval(" + json.dumps(setup + source) + "))"],
                text=True,
                capture_output=True,
                check=True,
                timeout=5,
            )
            return json.loads(completed.stdout)

        transport.native = native
        try:
            return await transport.close_tab("terminal:101:ttys001")
        finally:
            self.assertEqual(calls, [True], "A close request must never be replayed")

    async def test_absent_target_and_preserved_other_window_confirm_close(self):
        result = await self.close("closed")
        self.assertIs(result["closed"], True)
        self.assertEqual(result["remaining"], 1)

    async def test_pending_confirmation_dialog_does_not_report_success(self):
        with self.assertRaises(UncertainExecution) as raised:
            await self.close("pending")
        self.assertEqual(raised.exception.code, "session_close_unconfirmed")

    async def test_removing_another_window_does_not_report_success(self):
        with self.assertRaises(subprocess.CalledProcessError):
            await self.close("foreign_removed")

    async def test_only_window_is_preserved(self):
        with self.assertRaises(subprocess.CalledProcessError):
            await self.close("only")
