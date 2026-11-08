"""Human-only presenter lifecycle; no terminal, subprocess or service is started."""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge.install_ui import SetupUI


def design(*, motion):
    controllers = []

    class Controller:
        def __init__(self, options):
            self.done = False
            self.index = 0
            self.motion = options.motion
            controllers.append(self)

        def poll(self):
            if self.done:
                return None
            if not self.motion:
                return self.finish()
            self.index += 1
            return f"FRAME {self.index}\n"

        def finish(self):
            if self.done:
                return ""
            self.done = True
            return "FULL KiraBridge\n"

        def cancel(self):
            self.done = True

    return SimpleNamespace(
        options_for=lambda stream, **kwargs: SimpleNamespace(
            motion=motion and kwargs.get("motion") != "reduced"
        ),
        static_banner=lambda options: "FULL KiraBridge\n",
        AnimationController=Controller,
        controllers=controllers,
    )


def test_static_presenter_is_stderr_only_and_prints_banner_once(capsys):
    module = design(motion=False)
    ui = SetupUI("en", design=module)
    ui.begin()
    ui.tick()
    ui.finish()
    ui.say("Prüfung", "Real check")
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "FULL KiraBridge\nReal check\n"


def test_polling_animation_prioritizes_real_status_prompt_and_error(monkeypatch):
    monkeypatch.setattr("os.get_terminal_size", lambda fd: os.terminal_size((80, 24)))

    class Terminal(io.StringIO):
        def isatty(self):
            return True

        def fileno(self):
            return 99

    stream = Terminal()
    module = design(motion=True)
    ui = SetupUI("en", stream, design=module, exclusive_output=True)
    ui.begin()
    ui.tick()
    assert stream.getvalue() == "FRAME 1\n\x1b[1FFRAME 2\n"
    ui.say("Echte Prüfung", "Real check")
    ui.tick()
    monkeypatch.setattr("builtins.input", lambda: "yes")
    assert ui.prompt("Fortfahren", "Continue") == "yes"
    ui.error("Fehler", "Real error")
    ui.tick()
    assert stream.getvalue() == "FRAME 1\n\x1b[1FFRAME 2\nReal check\nContinue: Real error\n"
    assert module.controllers[0].done


def test_graphic_write_failure_cannot_prevent_real_status():
    class BrokenGraphic(io.StringIO):
        def write(self, value):
            if "KiraBridge" in value:
                raise BrokenPipeError("Synthetic decorative write failure")
            return super().write(value)

    stream = BrokenGraphic()
    ui = SetupUI("en", stream, design=design(motion=False))
    ui.begin()
    ui.say("Prüfung", "Real check")
    assert stream.getvalue() == "\nReal check\n"


@pytest.mark.parametrize("failure", ["broken", "interrupt"])
def test_partial_colored_write_resets_tty_without_swallowing_interrupt(failure):
    class Interrupted(io.StringIO):
        def isatty(self):
            return True

        def fileno(self):
            return 99

        def write(self, value):
            if value == "\x1b[35mPARTIAL":
                super().write(value)
                if failure == "interrupt":
                    raise KeyboardInterrupt
                raise BrokenPipeError("Isolated fixture")
            return super().write(value)

    stream = Interrupted()
    ui = SetupUI("en", stream, design=design(motion=False))
    if failure == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            ui._graphic("\x1b[35mPARTIAL")
    else:
        ui._graphic("\x1b[35mPARTIAL")
    # Cancellation records an opaque cleanup prefix; the real-output caller must
    # transmit it completely before acknowledging it, not retry graphic bytes.
    assert ui.output_prefix.startswith("\x18\x1b[0m")
    ui.error("Fehler", "Real error")
    assert not ui.output_prefix
    assert stream.getvalue().endswith("\x1b[0m\nReal error\n")


@pytest.fixture
def packaged_presenter(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = root / "installer/presentation.py"
    spec = importlib.util.spec_from_file_location("isolated_presentation_loader", source)
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    fake = b"""from types import SimpleNamespace
def options_for(stream, **kwargs): return SimpleNamespace(motion=False)
def static_banner(options): return 'FULL KiraBridge\\n'
class AnimationController:
 def __init__(self, options): self.done=False
 def poll(self): return self.finish()
 def finish(self):
  if self.done: return ''
  self.done=True
  return 'FULL KiraBridge\\n'
 def cancel(self): self.done=True
"""
    assets = {
        loader.ASSETS[0]: fake,
        loader.ASSETS[1]: (root / "src/kirabridge/install_ui.py").read_bytes(),
        loader.ASSETS[2]: source.read_bytes(),
    }
    hashes = {}
    for name, body in assets.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        hashes[name] = hashlib.sha256(body).hexdigest()
    (tmp_path / "release.json").write_text(
        json.dumps(
            {
                "presentation": {"schema": loader.SCHEMA, "assets": hashes},
                "files": hashes,
            }
        )
    )
    return loader, tmp_path


def test_bundled_loader_verifies_every_asset_before_importing_any_code(packaged_presenter):
    loader, bundle = packaged_presenter
    stream = io.StringIO()
    ui = loader.create_presentation(bundle, language="en", stream=stream)
    assert ui is not None
    ui.begin()
    assert stream.getvalue() == "FULL KiraBridge\n"
    marker = bundle / "must-not-execute"
    (bundle / loader.ASSETS[1]).write_text(
        "from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n"
    )
    assert loader.create_presentation(bundle) is None
    assert not marker.exists()


def test_bundled_loader_executes_verified_bytes_despite_later_file_change(
    packaged_presenter, monkeypatch
):
    loader, bundle = packaged_presenter
    target = bundle / loader.ASSETS[0]
    marker = bundle / "must-not-execute"
    original = Path.read_bytes

    def replace_after_read(path):
        result = original(path)
        if path == target:
            path.write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n")
        return result

    monkeypatch.setattr(Path, "read_bytes", replace_after_read)
    stream = io.StringIO()
    ui = loader.create_presentation(bundle, language="en", stream=stream)
    assert ui is not None
    ui.begin()
    assert stream.getvalue() == "FULL KiraBridge\n"
    assert not marker.exists()


def test_pinned_real_renderer_works_through_early_bundle_presenter(
    packaged_presenter, monkeypatch, capsys
):
    loader, bundle = packaged_presenter
    default = Path(__file__).resolve().parents[1] / "src/kirabridge/terminal_design.py"
    source = Path(os.environ.get("KIRABRIDGE_TEST_TERMINAL_DESIGN_SOURCE", str(default)))
    if not source.is_file():
        pytest.skip(
            "Renderer dependency branch must be integrated or explicitly pinned for this test"
        )
    body = source.read_bytes()
    (bundle / loader.ASSETS[0]).write_bytes(body)
    pin_path = bundle / "release.json"
    pin = json.loads(pin_path.read_text())
    pin["presentation"]["assets"][loader.ASSETS[0]] = hashlib.sha256(body).hexdigest()
    pin["files"][loader.ASSETS[0]] = hashlib.sha256(body).hexdigest()
    pin_path.write_text(json.dumps(pin))

    class Terminal(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True

        def fileno(self):
            return 99

    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.setenv("KIRABRIDGE_MOTION", "full")
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = Terminal()
    monkeypatch.setattr("os.get_terminal_size", lambda fd: os.terminal_size((80, 24)))
    ui = loader.create_presentation(bundle, stream=stream, exclusive_output=True)
    assert ui is not None
    assert ui.design.PINK == (240, 109, 176)
    clock = [0.0]
    real_controller = ui.design.AnimationController
    ui.design.AnimationController = lambda options: real_controller(options, clock=lambda: clock[0])
    ui.begin()
    first = stream.getvalue()
    assert first and "\x1b[38;2;" in first
    clock[0] = 0.3
    ui.tick()
    assert stream.getvalue() != first
    clock[0] = 0.6
    ui.tick()
    # The installer header is the compact wordmark of the same pinned design.
    final = ui.design.static_banner(
        ui.design.options_for(stream, width=79, motion="auto", compact=True)
    )
    assert stream.getvalue().endswith(final)
    assert "⣿" in final and final.count("\n") == 5
    ui.say("Echte Prüfung")
    after = stream.getvalue()
    ui.tick()
    assert stream.getvalue() == after and after.endswith("Echte Prüfung\n")
    assert capsys.readouterr().out == ""


def test_animation_never_redraws_after_resize_or_without_exclusive_output(monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

        def fileno(self):
            return 99

    size = [os.terminal_size((80, 24))]
    queried = []

    def viewport(fd):
        queried.append(fd)
        return size[0]

    monkeypatch.setattr("os.get_terminal_size", viewport)
    stream = Terminal()
    module = design(motion=True)
    ui = SetupUI("en", stream, design=module, exclusive_output=True)
    ui.begin()
    before = stream.getvalue()
    size[0] = os.terminal_size((60, 20))
    ui.tick()
    assert stream.getvalue() == before
    assert queried and set(queried) == {99}
    ui.say("Echter Status", "Real status")
    assert stream.getvalue() == before + "Real status\n"
    plain = Terminal()
    unowned = SetupUI("en", plain, design=module)
    unowned.begin()
    unowned.tick()
    assert plain.getvalue() == "FULL KiraBridge\n" and "\x1b" not in plain.getvalue()


def test_unknown_stderr_viewport_disables_redraw_instead_of_using_stdout_size(monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

        def fileno(self):
            return 99

    def unavailable(fd):
        assert fd == 99
        raise OSError("No owned viewport")

    monkeypatch.setattr("os.get_terminal_size", unavailable)
    monkeypatch.setattr("shutil.get_terminal_size", lambda *a, **k: os.terminal_size((160, 60)))
    stream = Terminal()
    ui = SetupUI("en", stream, design=design(motion=True), exclusive_output=True)
    ui.begin()
    ui.tick()
    assert stream.getvalue() == "FULL KiraBridge\n"
    assert "\x1b" not in stream.getvalue()


class Console(io.StringIO):
    encoding = "utf-8"

    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


def structured(ui):
    ui.heading("KiraBridge · Installation", meta="0.8.0rc42 · 3f9c2a1")
    ui.phase("Paket prüfen")
    ui.ok("Prüfsummen stimmen", detail="241 Dateien · Version 0.8.0rc42")
    ui.ok(
        "Laufzeit eingerichtet",
        detail="~/.local/share/kirabridge/install/releases/0.8.0rc42-3f9c2a1b7d40"
        " · bisherige Installation unverändert",
    )
    ui.warn("Umschaltung fehlgeschlagen")
    ui.summary("KiraBridge 0.8.0rc42 ist installiert", rows=[("Quellstand", "3f9c2a1b7d40")])
    ui.error("FEHLER: Beispiel")


def test_structured_output_is_plain_without_a_color_terminal(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = Console(tty=False)
    structured(SetupUI("de", stream, design=design(motion=False)))
    text = stream.getvalue()
    assert "\x1b" not in text
    assert "\n  1  Paket prüfen\n" in text
    assert "     ✓ Prüfsummen stimmen\n       241 Dateien · Version 0.8.0rc42\n" in text
    # A path is never split at its hyphens; long details put each part on its own line.
    assert "       ~/.local/share/kirabridge/install/releases/0.8.0rc42-3f9c2a1b7d40\n" in text
    assert "       bisherige Installation unverändert\n" in text
    assert "     ! Umschaltung fehlgeschlagen\n" in text
    assert "  ✓ KiraBridge 0.8.0rc42 ist installiert\n    Quellstand   3f9c2a1b7d40\n" in text
    assert text.rstrip().endswith("✗ FEHLER: Beispiel")


@pytest.mark.parametrize("variable", ["NO_COLOR", "TERM"])
def test_structured_output_honours_no_color_and_dumb_terminals(monkeypatch, variable):
    monkeypatch.setenv("TERM", "dumb" if variable == "TERM" else "xterm-256color")
    if variable == "NO_COLOR":
        monkeypatch.setenv("NO_COLOR", "1")
    stream = Console(tty=True)
    structured(SetupUI("de", stream, design=design(motion=False)))
    assert "\x1b" not in stream.getvalue()


def test_structured_output_is_colored_on_an_interactive_terminal(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = Console(tty=True)
    structured(SetupUI("de", stream, design=design(motion=False)))
    text = stream.getvalue()
    assert "\x1b[1m\x1b[38;2;240;109;176m1\x1b[0m" in text  # phase number in brand pink
    assert "\x1b[38;2;94;196;140m✓\x1b[0m" in text
    assert text.count("\x1b[0m") >= text.count("\x1b[1m")


def test_ascii_only_stream_uses_ascii_marks(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = Console(tty=False)
    stream.encoding = "ascii"
    ui = SetupUI("de", stream, design=design(motion=False))
    ui.phase("Paket")
    ui.ok("Fertig")
    assert "     + Fertig\n" in stream.getvalue()


def test_fail_and_hint_lines(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = Console(tty=False)
    ui = SetupUI("de", stream, design=design(motion=False))
    ui.phase("Dienste")
    ui.fail("Kaputt", detail="Exit 1", hint="In der Konsole starten")
    assert "     ✗ Kaputt\n       Exit 1\n       → In der Konsole starten\n" in stream.getvalue()
