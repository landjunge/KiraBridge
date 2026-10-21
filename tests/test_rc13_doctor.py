"""Doctor behavior is scoped and cannot restart unrelated services."""
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "kirabridge-doctor.sh"

def test_doctor_defaults_to_read_only_check():
    content = SCRIPT.read_text()
    assert 'MODE="${1:-check}"' in content
    assert 'if [[ "$MODE" == "restart" ]]; then' in content
    assert '"$CLI" status' in content

def test_restart_is_scoped_to_bridge_label():
    content = SCRIPT.read_text()
    assert 'LABEL="com.kirabridge.bridge"' in content
    assert 'launchctl bootout "$TARGET/$LABEL"' in content
    assert 'launchctl bootstrap "$TARGET" "$PLIST"' in content
    assert "killall" not in content
