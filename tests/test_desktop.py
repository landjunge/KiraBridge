import asyncio
import os
import sys
from pathlib import Path

import pytest
from conftest import request, submit

from kirabridge.bridge_core.models import BridgeError
from kirabridge.clipboard_manager import ClipboardManager
from kirabridge.filesystem_manager import FilesystemManager, PathScope


def test_scoped_file_lifecycle(tmp_path):
    scope = PathScope([str(tmp_path)])
    files = FilesystemManager()
    folder = str(tmp_path / "folder")
    files.mkdir(scope, folder)
    first, second = folder + "/first.txt", folder + "/second.txt"
    text = "Grüße 👋\n第二行\n"
    assert files.write(scope, first, text, False)["written_bytes"] == len(text.encode())
    assert files.read(scope, first, 1024)["text"] == text
    assert files.read(scope, first, 3)["truncated"]
    with pytest.raises(FileExistsError):
        files.write(scope, first, "wrong", False)
    assert files.read(scope, first, 1024)["text"] == text
    files.write(scope, first, "updated", True)
    files.move(scope, first, second)
    assert files.list(scope, folder)["entries"][0]["name"] == "second.txt"
    files.delete(scope, second)
    files.delete(scope, folder)
    assert files.list(scope, str(tmp_path))["entries"] == []


@pytest.mark.parametrize("relative", ["../outside", "sub/../../outside"])
def test_path_traversal_rejected(tmp_path, relative):
    with pytest.raises(BridgeError):
        PathScope([str(tmp_path)]).split(str(tmp_path) + "/" + relative)


def test_symlink_escape_and_special_files(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret").write_text("private")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    (root / "secret").symlink_to(outside / "secret")
    scope, files = PathScope([str(root)]), FilesystemManager()
    with pytest.raises((BridgeError, OSError)):
        files.read(scope, str(root / "escape/secret"), 1024)
    with pytest.raises((BridgeError, OSError)):
        files.read(scope, str(root / "secret"), 1024)
    with pytest.raises((BridgeError, OSError)):
        files.write(scope, str(root / "secret"), "changed", True)
    os.mkfifo(root / "fifo")
    with pytest.raises(BridgeError, match="regular"):
        files.read(scope, str(root / "fifo"), 1024)
    assert (outside / "secret").read_text() == "private"


def test_no_root_deletion_or_implicit_overwrite(tmp_path):
    scope, files = PathScope([str(tmp_path)]), FilesystemManager()
    with pytest.raises(BridgeError):
        files.delete(scope, str(tmp_path))
    (tmp_path / "a").write_text("a")
    (tmp_path / "b").write_text("b")
    with pytest.raises(FileExistsError):
        files.move(scope, str(tmp_path / "a"), str(tmp_path / "b"))
    assert (tmp_path / "a").read_text() == "a"
    assert (tmp_path / "b").read_text() == "b"


async def run_terminal(bridge, config, code, **options):
    value = request(
        "terminal.execute",
        {
            "argv": [sys.executable, "-c", code],
            "cwd": config.principals["local"].roots[0],
            **options,
        },
    )
    async with bridge:
        submit(bridge, value)
        return await bridge.tasks.wait("local", value.task_id, 10)


async def test_terminal_exit_output_cwd_and_environment(bridge, config, monkeypatch):
    monkeypatch.setenv("PRIVATE_TEST_SECRET", "must-not-inherit")
    final = await run_terminal(
        bridge,
        config,
        "import os,sys; print(os.getcwd()); print(os.getenv('PRIVATE_TEST_SECRET')); "
        "print('err',file=sys.stderr); sys.exit(7)",
    )
    assert final["state"] == "failed"
    assert final["result"]["exit_code"] == 7
    assert config.principals["local"].roots[0] in final["result"]["stdout"]
    assert "None" in final["result"]["stdout"]
    assert "err" in final["result"]["stderr"]


async def test_terminal_bounded_output(bridge, config):
    final = await run_terminal(bridge, config, "print('x'*200000)", max_output=256)
    assert final["state"] == "completed"
    assert len(final["result"]["stdout"].encode()) <= 256
    assert final["result"]["truncated"]
    assert final["result"]["output_bytes"] > 200000


async def test_timeout_kills_own_process(bridge, config):
    final = await run_terminal(bridge, config, "import time; time.sleep(60)", timeout=0.1)
    assert final["state"] == "failed"
    assert final["result"]["timed_out"]
    assert final["result"]["exit_code"] != 0
    assert not bridge.terminal.sessions


async def test_executable_denied_before_execution(bridge, config):
    config.principals["local"].executables = []
    final = await run_terminal(bridge, config, "print('must not execute')")
    assert final["state"] == "failed" and final["started"] is None
    assert final["error"]["code"] == "executable_denied"
    assert final["evidence"]["safe_to_retry"]


async def test_terminal_shell_metacharacters_are_literal(bridge, config):
    value = request(
        "terminal.execute",
        {
            "argv": [
                sys.executable,
                "-c",
                "import sys; print(sys.argv[1])",
                "$(touch injected); echo unsafe",
            ],
            "cwd": config.principals["local"].roots[0],
        },
    )
    async with bridge:
        submit(bridge, value)
        final = await bridge.tasks.wait("local", value.task_id)
        assert "$(touch injected); echo unsafe" in final["result"]["stdout"]
        assert not Path(config.principals["local"].roots[0], "injected").exists()


async def test_termination_control_lane_survives_saturation(bridge, config):
    config.concurrency = 1
    value = request(
        "terminal.execute",
        {
            "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
            "cwd": config.principals["local"].roots[0],
        },
    )
    async with bridge:
        submit(bridge, value)
        async with asyncio.timeout(5):
            while bridge.store.get(value.task_id)["state"] != "running":
                await asyncio.sleep(0.01)
        assert bridge.terminal.inspect("local", value.task_id)["alive"]
        with pytest.raises(BridgeError):
            bridge.terminal.inspect("other", value.task_id)
        submit(bridge, request("process.terminate", {"task_id": value.task_id}, task_id="stop"))
        stopped = await bridge.tasks.wait("local", "stop", 5)
        assert stopped["state"] == "completed"
        final = await bridge.tasks.wait("local", value.task_id, 5)
        assert final["state"] == "failed"
        assert final["result"]["terminated"]


class TestClipboardPlatform:
    __test__ = False
    name = "test"

    def __init__(self, target):
        self.target = target

    def clipboard_command(self, write):
        code = "import sys; from pathlib import Path; p=Path(sys.argv[1]); " + (
            "p.write_bytes(sys.stdin.buffer.read())"
            if write
            else "sys.stdout.buffer.write(p.read_bytes())"
        )
        return [sys.executable, "-c", code, str(self.target)]


async def test_clipboard_unicode_multiline_confirmation_and_limit(tmp_path):
    manager = ClipboardManager(TestClipboardPlatform(tmp_path / "clipboard"))
    text = "äöü\n🔐 日本語\n" * 10000
    result = await manager.write(text)
    assert result["verified"]
    assert (await manager.read(1048576))["text"] == text
    with pytest.raises(BridgeError, match="limit"):
        await manager.read(10)
    with pytest.raises(BridgeError):
        await manager.write("🔐" * 1048576)


def test_clipboard_info_never_reads_contents(tmp_path):
    manager = ClipboardManager(TestClipboardPlatform(tmp_path / "nonexistent"))
    assert not manager.info()["content_read"]
    assert not manager.info()["monitoring"]
    assert not (tmp_path / "nonexistent").exists()
