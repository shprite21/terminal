import warnings
from unittest.mock import Mock
import pytest
from evidence import cli


@pytest.fixture
def local_setup(monkeypatch):
    import keyring
    writer = Mock()
    monkeypatch.setattr(keyring, "set_password", writer)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "")
    return writer


def test_empty_input_reprompts_without_partial_save(monkeypatch, local_setup, capsys):
    entries = iter(["", " ", "test-api-key", "test-client", "test-pin"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: next(entries))
    cli.configure_credentials()
    assert local_setup.call_count == 3
    output = capsys.readouterr().out
    assert "API_KEY was empty" in output
    assert "Saved in OS credential store" in output
    assert all(secret not in output for secret in ("test-api-key", "test-client", "test-pin"))


def test_cancel_after_api_key_saves_nothing(monkeypatch, local_setup):
    entries = iter(["test-api-key"])
    def read(_):
        try:
            return next(entries)
        except StopIteration:
            raise KeyboardInterrupt
    monkeypatch.setattr(cli.getpass, "getpass", read)
    with pytest.raises(cli.SetupError, match="cancelled before saving"):
        cli.configure_credentials()
    local_setup.assert_not_called()


def test_visible_setup_saves_entered_values_without_hidden_prompt(monkeypatch, local_setup):
    entries = iter(["", " test-api-key ", "test-client", "test-pin", "YES", "test-seed"])
    monkeypatch.setattr("builtins.input", lambda _: next(entries))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: pytest.fail("Visible mode must not use hidden input"))
    cli.configure_credentials(show_input=True)
    assert [call.args for call in local_setup.call_args_list] == [
        ("evidence-angel-one", field, value) for field, value in
        [("API_KEY", "test-api-key"), ("CLIENT_CODE", "test-client"), ("PIN", "test-pin"), ("TOTP_SEED", "test-seed")]
    ]


def test_repeated_empty_field_identified(monkeypatch, local_setup):
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "")
    with pytest.raises(cli.SetupError, match="API_KEY was empty after three attempts"):
        cli.configure_credentials()
    local_setup.assert_not_called()


def test_hidden_input_fallback_refused(monkeypatch, local_setup):
    def read(_):
        warnings.warn("Input may be echoed", cli.getpass.GetPassWarning)
        pytest.fail("Echoing fallback should never run")
    monkeypatch.setattr(cli.getpass, "getpass", read)
    with pytest.raises(cli.SetupError, match="Hidden input is unavailable"):
        cli.configure_credentials()
    local_setup.assert_not_called()


def test_piped_credentials_refused(monkeypatch, local_setup):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    with pytest.raises(cli.SetupError, match="interactive PowerShell"):
        cli.configure_credentials()
    local_setup.assert_not_called()


def test_keyring_error_does_not_expose_backend_details(monkeypatch, local_setup):
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "test-private-value")
    local_setup.side_effect = RuntimeError("backend included test-private-value")
    with pytest.raises(cli.SetupError) as caught:
        cli.configure_credentials()
    assert "test-private-value" not in str(caught.value)
    assert "may be partial" in str(caught.value)


def test_test_temp_directory_is_fresh_and_bypasses_shared_root(tmp_path, pytestconfig):
    assert tmp_path.is_dir()
    base = tmp_path.parent
    if base.name.startswith("evidence-pytest-"):
        assert not any(parent.name.startswith("pytest-of-") for parent in base.parents)
    assert not pytestconfig.pluginmanager.hasplugin("cacheprovider")
