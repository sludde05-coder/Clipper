import tomllib

from clipper import setup_wizard as w

EXAMPLE = open("config.example.toml", encoding="utf-8").read()


def test_set_value_keeps_comments_and_other_sections():
    t = w.set_value(EXAMPLE, "twitch", "client_id", "abc123")
    t = w.set_value(t, "kick", "client_id", "kick-id")
    t = w.set_value(t, "anthropic", "api_key", 'sk-ant-x"y')
    data = tomllib.loads(t)
    assert data["twitch"]["client_id"] == "abc123"
    assert data["twitch"]["client_secret"] == ""
    assert data["kick"]["client_id"] == "kick-id"
    assert data["anthropic"]["api_key"] == 'sk-ant-x"y'
    assert data["discovery"]["top_n"] == 10
    assert "# Copy to config.toml" in t
    assert t.count("[twitch]") == 1


def test_set_value_adds_missing_section_and_key():
    t = w.set_value("[twitch]\n", "twitch", "client_id", "a")
    t = w.set_value(t, "youtube", "api_key", "b")
    assert tomllib.loads(t) == {"twitch": {"client_id": "a"}, "youtube": {"api_key": "b"}}


def test_wizard_saves_checked_keys(tmp_path, monkeypatch):
    (tmp_path / "config.example.toml").write_text(EXAMPLE, encoding="utf-8")
    monkeypatch.setattr(w.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(w.SERVICES[0], "check", lambda v: (False, "was rejected") if v["client_id"] == "bad"
                        else (True, "works"))
    monkeypatch.setattr(w.SERVICES[3], "check", lambda v: (None, "couldn't be checked"))
    answers = iter([
        "",                 # Twitch: set up now? (default yes)
        "bad", "s1",        # wrong id...
        "",                 # try again? yes
        " 'good' ", "s2",   # pasted with junk around it
        "n",                # YouTube: no
        "",                 # Kick: default no
        "y", "sk-ant-1",    # Anthropic: yes, can't be checked -> saved anyway
    ])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    w.run_wizard(str(tmp_path / "config.toml"))
    data = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert data["twitch"] == {"client_id": "good", "client_secret": "s2"}
    assert data["youtube"]["api_key"] == ""
    assert data["anthropic"]["api_key"] == "sk-ant-1"
