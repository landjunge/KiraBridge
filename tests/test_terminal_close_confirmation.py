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
                let boundReads = 0;
                function peerBounds(id) {
                    if (mode === 'missing_bounds') return null;
                    if (mode === 'invalid_bounds') return {x: 0, y: 0, width: NaN, height: 600};
                    return {x: id === 101 || mode === 'shared_surface'
                                      ? (mode === 'negative_origin' ? -900 : 0) : 900,
                            y: mode === 'negative_origin' ? -600 : 0,
                            width: mode === 'bounds_changed' && ++boundReads > 3
                                           ? 801 : 800, height: 600};
                }
                function tty(id) {
                    return mode === 'duplicate_tty' || id === 101 ? '/dev/ttys001' : '/dev/ttys002';
                }
                const app = {windows: () => ids.map(id => ({
                    id: () => id, bounds: () => peerBounds(id),
                    tabs: () => [{tty: () => tty(id)}]
                }))};
                const targetWindow = {
                    id: () => 101,
                    bounds: () => peerBounds(101),
                    tabs: () => mode === 'multi_tab' ? [{}, {}] : [{tty: () => '/dev/ttys001'}],
                    close: () => {
                        if (['shared_surface', 'missing_bounds', 'invalid_bounds',
                             'bounds_changed', 'duplicate_tty'].includes(mode))
                            throw Error('Unexpected close of unconfirmed surface');
                        if (mode === 'busy') throw Error('Unexpected close of busy tab');
                        if (mode === 'multi_tab')
                            throw Error('Unexpected close of multi-tab window');
                        if (mode === 'closed' || mode === 'negative_origin') ids = [202];
                        if (mode === 'foreign_removed') ids = [];
                    }
                };
                const tab = {busy: () => mode === 'busy'};
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

    async def test_multi_tab_window_is_refused_before_close_attempt(self):
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            await self.close("multi_tab")
        self.assertIn("Refusing to close a multi-tab Terminal window", raised.exception.stderr)
        self.assertNotIn("Unexpected close of multi-tab window", raised.exception.stderr)

    async def test_busy_tab_is_refused_before_terminal_dialog(self):
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            await self.close("busy")
        self.assertIn("Selected terminal is busy", raised.exception.stderr)
        self.assertNotIn("Unexpected close of busy tab", raised.exception.stderr)

    async def test_shared_scripting_surface_or_unknown_binding_never_closes(self):
        for mode in (
            "shared_surface",
            "missing_bounds",
            "invalid_bounds",
            "bounds_changed",
            "duplicate_tty",
        ):
            with self.subTest(mode=mode):
                with self.assertRaises(subprocess.CalledProcessError) as raised:
                    await self.close(mode)
                expected = {
                    "shared_surface": "shared or ambiguous Terminal surface",
                    "missing_bounds": "Close surface bounds are unavailable",
                    "invalid_bounds": "Close surface bounds are unavailable",
                    "bounds_changed": "Close target bounds changed",
                    "duplicate_tty": "Close target TTY binding changed",
                }
                self.assertIn(expected[mode], raised.exception.stderr)
                self.assertNotIn("Unexpected close of unconfirmed surface", raised.exception.stderr)

    async def test_negative_monitor_coordinates_preserve_valid_standalone_close(self):
        result = await self.close("negative_origin")
        self.assertIs(result["closed"], True)
        self.assertEqual(result["remaining"], 1)
