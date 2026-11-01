from pathlib import Path

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.filesystem_manager import FilesystemManager, PathScope


@pytest.mark.parametrize("operation", ["read", "list", "write", "delete", "mkdir", "move"])
def test_ordinary_file_operations_cannot_access_move_recovery(tmp_path, operation):
    root = tmp_path.resolve()
    stage = root / (".kirabridge-move-" + "a" * 32)
    stage.mkdir(mode=0o700)
    payload = stage / "retained"
    payload.write_text("recovery data")
    source = root / "ordinary"
    source.write_text("ordinary data")
    scope, manager = PathScope([str(root)]), FilesystemManager()
    calls = {
        "read": lambda: manager.read(scope, str(payload), 100),
        "list": lambda: manager.list(scope, str(stage)),
        "write": lambda: manager.write(scope, str(payload), "changed", True),
        "delete": lambda: manager.delete(scope, str(payload)),
        "mkdir": lambda: manager.mkdir(scope, str(stage / "new")),
        "move": lambda: manager.move(scope, str(source), str(stage / "new")),
    }
    with pytest.raises(BridgeError) as error:
        calls[operation]()
    assert error.value.code == "path_denied"
    assert payload.read_text() == "recovery data"
    assert source.read_text() == "ordinary data"


@pytest.mark.parametrize("name", [".kirabridge-move-not-a-transaction", ".kirabridge-move-ab"])
def test_similarly_named_user_files_are_not_reserved(tmp_path, name):
    root = tmp_path.resolve()
    path = root / name
    path.write_text("ordinary data")
    result = FilesystemManager().read(PathScope([str(root)]), str(path), 100)
    assert result["text"] == "ordinary data"


@pytest.mark.parametrize("prefix", [".kirabridge-move-", ".KIRABRIDGE-MOVE-", ".Kirabridge-move-"])
def test_nested_move_recovery_namespace_is_private_even_as_an_allowed_root(tmp_path, prefix):
    stage = tmp_path.resolve() / (prefix + "b" * 32)
    stage.mkdir(mode=0o700)
    scope = PathScope([str(stage)])
    with pytest.raises(BridgeError) as error:
        scope.split(str(stage / "payload"))
    assert error.value.code == "path_denied"
    assert Path(stage).is_dir()
