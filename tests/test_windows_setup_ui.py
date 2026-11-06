"""Headless presenter/widget guards; no Tk window, browser or network."""

import json
import threading
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.windows_setup_ui import (
    ERROR_MESSAGES,
    OFFICIAL_PAGES,
    SetupState,
    WindowsSetupApp,
    WindowsSetupPresenter,
)


class View:
    def __init__(self):
        self.states, self.copies = [], []
        self.key_cleared = self.code_cleared = self.closed = 0
        self.owner = threading.get_ident()

    def render(self, state):
        assert threading.get_ident() == self.owner
        self.states.append(state)

    def clear_runtime_key(self):
        assert threading.get_ident() == self.owner
        self.key_cleared += 1

    def clear_response_code(self):
        assert threading.get_ident() == self.owner
        self.code_cleared += 1

    def copy_public_text(self, text):
        self.copies.append(text)

    def close(self):
        self.closed += 1


class Controller:
    def __init__(self):
        self.calls, self.replies = [], {}
        self.close_calls = 0

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args))
            result = self.replies.get(name, {"state": "ready"})
            if isinstance(result, Exception):
                raise result
            return result

        return call

    def close(self):
        self.close_calls += 1


def fixture():
    controller, view, jobs, urls = Controller(), View(), [], []
    presenter = WindowsSetupPresenter(
        controller, view, submit=jobs.append, browser_open=lambda url: urls.append(url) or True
    )
    return presenter, controller, view, jobs, urls


def complete(presenter, jobs):
    jobs.pop(0)()
    presenter.poll()


def ready(presenter, controller, jobs):
    presenter.consent(True)
    controller.replies["inspect"] = {
        "state": "local_ready",
        "local_ready": True,
        "client_installed": True,
    }
    presenter.inspect()
    complete(presenter, jobs)
    controller.replies["connection_status"] = {"state": "tunnel_ready", "tunnel_ready": True}
    presenter.connection_status()
    complete(presenter, jobs)


def challenge(presenter, controller, jobs):
    ready(presenter, controller, jobs)
    controller.replies["begin_verification"] = {
        "state": "verification_pending",
        "prompt": "Bitte prüfe den frischen Rückweg.",
    }
    presenter.begin_verification()
    complete(presenter, jobs)


def test_no_default_consent_or_automatic_start_but_client_install_is_independent():
    p, c, v, jobs, _ = fixture()
    assert not p.state.consent and not c.calls
    assert not p.start_local() and not p.connect("tunnel_abcdefgh", "key" * 20)
    p.account_help(True)
    c.replies["install_client"] = {"state": "client_installed", "client_installed": True}
    assert p.install_client()
    complete(p, jobs)
    assert p.state.client_ready and p.state.account_help and not p.state.verified
    assert [x[0] for x in c.calls] == ["install_client"] and not v.copies


def test_real_controller_flags_unlock_steps_without_claiming_chatgpt_success():
    p, c, _, jobs, _ = fixture()
    ready(p, c, jobs)
    assert p.state.local_ready and p.state.client_ready and p.state.connected
    assert not p.state.verified
    c.replies["connection_status"] = {
        "state": "tunnel_pending",
        "tunnel_ready": False,
        "message": "Noch nicht bereit. Fenster offen lassen.",
    }
    p.connection_status()
    complete(p, jobs)
    assert not p.state.connected and "Fenster offen" in p.state.message


def test_lost_local_instance_and_expired_code_remove_stale_success_indicators():
    p, c, _, jobs, _ = fixture()
    challenge(p, c, jobs)
    c.replies["finish_verification"] = BridgeError("setup_verification_expired", "secret")
    p.finish_verification("old-code")
    complete(p, jobs)
    assert not p.state.verified and not p.state.verification_pending and not p.state.prompt
    c.replies["inspect"] = {
        "state": "windows_ready",
        "local_ready": False,
        "client_installed": False,
    }
    p.inspect()
    complete(p, jobs)
    assert not p.state.connected and not p.state.local_ready and not p.state.client_ready


def test_key_clears_before_worker_and_never_enters_view_or_logs(capsys):
    p, c, v, jobs, _ = fixture()
    p.consent(True)
    secret = "runtime-secret-" * 4
    c.replies["connect"] = {"state": "tunnel_ready", "runtime_key": secret}
    assert p.connect("tunnel_abcdefgh", secret)
    assert v.key_cleared == 1 and not c.calls
    assert p.state.busy and not p.inspect() and not p.start_local() and not p.close()
    assert not p.go(2) and not p.open_page("keys")
    complete(p, jobs)
    assert c.calls == [("connect", ("tunnel_abcdefgh", secret))]
    assert p.state.connected and not p.state.verified
    assert secret not in json.dumps([asdict(x) for x in v.states])
    assert secret not in capsys.readouterr().err


def test_secret_echo_and_exception_text_are_not_rendered_or_printed(capsys):
    for result in (
        {"state": "error", "message": "private-key-" * 4},
        RuntimeError("private-key-" * 4),
    ):
        p, c, v, jobs, _ = fixture()
        p.consent(True)
        c.replies["connect"] = result
        p.connect("tunnel_abcdefgh", "private-key-" * 4)
        complete(p, jobs)
        assert "private-key-" not in json.dumps([asdict(x) for x in v.states])
        assert "connect" in p.state.blocked_operations
        assert not p.connect("tunnel_abcdefgh", "private-key-" * 4)
    captured = capsys.readouterr()
    assert "private-key-" not in captured.out + captured.err


@pytest.mark.parametrize("code", ERROR_MESSAGES)
def test_known_backend_errors_use_fixed_actionable_text_without_raw_exception(code):
    p, c, _, jobs, _ = fixture()
    c.replies["inspect"] = BridgeError(code, "secret account / URL / key")
    p.inspect()
    complete(p, jobs)
    assert p.state.message == ERROR_MESSAGES[code][0]
    assert p.state.next_action == ERROR_MESSAGES[code][1]
    assert "secret account" not in p.state.message + p.state.next_action


def test_only_fresh_finish_with_verified_true_can_mark_complete():
    p, c, v, jobs, _ = fixture()
    assert not p.finish_verification("old-code")
    ready(p, c, jobs)
    c.replies["inspect"] = {"state": "verified", "verified": True}
    p.inspect()
    complete(p, jobs)
    assert not p.state.verified
    challenge(p, c, jobs)
    assert p.copy_prompt() and v.copies == [p.state.prompt]
    c.replies["finish_verification"] = {"state": "verification_pending", "verified": False}
    p.finish_verification("wrong-code")
    complete(p, jobs)
    assert not p.state.verified and p.state.verification_pending
    c.replies["finish_verification"] = {"state": "verified", "verified": True}
    p.finish_verification("fresh-code")
    complete(p, jobs)
    assert p.state.verified and not p.state.verification_pending and v.code_cleared == 2


@pytest.mark.parametrize("state", ["local_test_verified", "verified"])
def test_simulation_never_turns_complete_green_even_with_verified_boolean(state):
    p, c, _, jobs, _ = fixture()
    challenge(p, c, jobs)
    c.replies["finish_verification"] = {"state": state, "verified": True, "simulated": True}
    p.finish_verification("simulated-code")
    complete(p, jobs)
    assert not p.state.verified and not p.state.verification_pending


def test_browser_opens_only_fixed_pages_on_explicit_click_and_does_not_claim_login():
    p, c, _, jobs, urls = fixture()
    assert not urls and not p.open_page("https://untrusted.example/")
    for page in OFFICIAL_PAGES:
        assert p.open_page(page) and len(jobs) == 1
        complete(p, jobs)
    assert urls == list(OFFICIAL_PAGES.values()) and not c.calls
    assert not p.state.connected and not p.state.verified


def test_real_worker_only_enqueues_until_main_thread_polls():
    c, v, finished = Controller(), View(), threading.Event()
    owner, worker_ids = threading.get_ident(), []

    def inspect():
        worker_ids.append(threading.get_ident())
        finished.set()
        return {"state": "windows_ready"}

    c.inspect = inspect
    p = WindowsSetupPresenter(c, v, browser_open=lambda _: pytest.fail("No browser allowed"))
    p.inspect()
    assert finished.wait(2)
    assert p.state.busy and len(v.states) == 2
    for _ in range(100):
        p.poll()
        if not p.state.busy:
            break
        threading.Event().wait(0.001)
    assert not p.state.busy and worker_ids != [owner]


def test_close_destroys_only_view_and_main_finally_releases_lease(monkeypatch):
    import kirabridge.windows_setup_ui as module

    p, c, v, _, _ = fixture()
    assert p.close() and v.closed == 1 and not c.calls and c.close_calls == 0
    root = SimpleNamespace(mainloop=lambda: None, destroy=lambda: None)
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setitem(module.sys.modules, "tkinter", SimpleNamespace(Tk=lambda: root))
    monkeypatch.setattr(module, "WindowsSetupApp", lambda *_: None)
    assert module.main(c) == 0 and c.close_calls == 1


def test_main_releases_lease_when_ui_creation_fails_without_echoing_exception(monkeypatch):
    import kirabridge.windows_setup_ui as module

    c, messages = Controller(), []
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setitem(module.sys.modules, "tkinter", SimpleNamespace(Tk=lambda: None))

    def broken(*_):
        raise RuntimeError("private account key")

    monkeypatch.setattr(module, "WindowsSetupApp", broken)
    monkeypatch.setattr(module, "_show_start_error", messages.append)
    assert module.main(c) == 1 and c.close_calls == 1
    assert "private account" not in messages[0]


class Widget:
    def __init__(self):
        self.options, self.value = {}, ""

    def configure(self, **options):
        self.options.update(options)

    def pack(self, **options):
        self.options.update(options)

    def pack_forget(self):
        pass

    def tkraise(self):
        pass

    def grid(self):
        self.options["mapped"] = True

    def grid_remove(self):
        self.options["mapped"] = False

    def set(self, value):
        self.value = value

    def delete(self, *args):
        self.value = ""

    def insert(self, where, value):
        self.value = value

    def start(self, interval):
        pass

    def stop(self):
        pass


def test_widget_policy_masks_key_and_disables_every_action_while_busy():
    app = WindowsSetupApp.__new__(WindowsSetupApp)
    widgets = []

    def entry(parent, **options):
        widget = Widget()
        widget.options.update(options)
        widgets.append(widget)
        return widget

    app.ttk, app.controls = SimpleNamespace(Entry=entry), []
    app._entry(None, object(), secret=True)
    assert widgets[0].options["show"]
    for name in (
        "start_button",
        "install_button",
        "connect_button",
        "saved_connect_button",
        "begin_button",
        "copy_button",
        "finish_button",
    ):
        setattr(app, name, Widget())
        app.controls.append(getattr(app, name))
    app.pages = [Widget() for _ in range(4)]
    app.message, app.next_action, app.finish_title = (Widget() for _ in range(3))
    app.account_help_label, app.account_help_anchor, app.prompt, app.progress = (
        Widget() for _ in range(4)
    )
    app._shown_prompt, app._progress_running = None, False
    app.render(SetupState(busy=True))
    assert [page.options["mapped"] for page in app.pages] == [True, False, False, False]
    assert all(w.options["state"] == "disabled" for w in app.controls)
    app.render(SetupState())
    assert app.start_button.options["state"] == "disabled"
    assert app.install_button.options["state"] == "normal"
    assert app.saved_connect_button.options["state"] == "disabled"
    app.render(SetupState(consent=True, local_ready=True, client_ready=True, connection_saved=True))
    assert app.saved_connect_button.options["state"] == "normal"
