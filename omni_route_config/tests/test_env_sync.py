"""env_sync — shell-env scan, secret generation, dotenv merge."""

from __future__ import annotations

from omni_route_config.catalog import ProviderCatalog, ProviderEntry
from omni_route_config.env_sync import (
    SERVER_DEFAULTS,
    SERVER_SECRETS,
    parse_dotenv,
    sync_env_file,
    write_dotenv,
)


def _cat() -> ProviderCatalog:
    return ProviderCatalog(
        providers=[
            ProviderEntry(provider="groq", env_var="GROQ_API_KEY"),
            ProviderEntry(provider="gemini", env_var="GEMINI_API_KEY"),
        ]
    )


# ---------- dotenv parser ----------


def test_parse_dotenv_handles_quotes_comments_blanks(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        '# comment\n\nKEY1=plain\nKEY2="quoted"\nKEY3=\'single\'\nKEY4=\nINVALID_LINE\n',
        encoding="utf-8",
    )
    out = parse_dotenv(p)
    assert out == {"KEY1": "plain", "KEY2": "quoted", "KEY3": "single", "KEY4": ""}


def test_parse_dotenv_missing_returns_empty(tmp_path):
    assert parse_dotenv(tmp_path / "nope") == {}


# ---------- write ordering ----------


def test_write_dotenv_section_order(tmp_path):
    p = tmp_path / ".env"
    write_dotenv(
        p,
        {"A": "1", "B": "2", "C": "3", "Z": "z"},
        section_order=[("Top", ["A", "B"]), ("Mid", ["C"])],
    )
    text = p.read_text(encoding="utf-8")
    assert text.index("# Top") < text.index("A=1") < text.index("# Mid")
    assert text.index("# Mid") < text.index("C=3") < text.index("# Other")
    assert text.index("# Other") < text.index("Z=z")


# ---------- sync_env_file ----------


def test_sync_first_run_generates_all_secrets(tmp_path):
    p = tmp_path / ".env"
    report = sync_env_file(p, catalog=_cat(), shell_env={"GROQ_API_KEY": "gsk_demo"})

    written = parse_dotenv(p)
    # Provider keys
    assert written["GROQ_API_KEY"] == "gsk_demo"
    assert written["GEMINI_API_KEY"] == ""  # blank slot for missing
    # Secrets
    for s in SERVER_SECRETS:
        assert written[s], f"secret {s} should have been generated"
    # INITIAL_PASSWORD is intentionally NOT auto-generated — surfaced blank.
    assert written["INITIAL_PASSWORD"] == ""
    # Defaults
    for k, v in SERVER_DEFAULTS.items():
        assert written[k] == v

    assert report.provider_keys_from_shell == ["GROQ_API_KEY"]
    assert report.provider_keys_missing == ["GEMINI_API_KEY"]
    assert set(report.secrets_generated) == set(SERVER_SECRETS)
    assert "INITIAL_PASSWORD" not in report.secrets_generated
    assert report.secrets_preserved == []


def test_sync_alias_falls_back_when_canonical_missing(tmp_path):
    from omni_route_config.catalog import ProviderCatalog, ProviderEntry

    cat = ProviderCatalog(
        providers=[
            ProviderEntry(
                provider="anthropic",
                env_var="ANTHROPIC_API_KEY",
                aliases=["CLAUDE_CONSOLE_API_KEY"],
            )
        ]
    )
    p = tmp_path / ".env"
    sync_env_file(p, catalog=cat, shell_env={"CLAUDE_CONSOLE_API_KEY": "sk-ant-via-alias"})
    after = parse_dotenv(p)
    assert after["ANTHROPIC_API_KEY"] == "sk-ant-via-alias"


def test_sync_canonical_wins_over_alias(tmp_path):
    from omni_route_config.catalog import ProviderCatalog, ProviderEntry

    cat = ProviderCatalog(
        providers=[
            ProviderEntry(
                provider="anthropic",
                env_var="ANTHROPIC_API_KEY",
                aliases=["CLAUDE_CONSOLE_API_KEY"],
            )
        ]
    )
    p = tmp_path / ".env"
    sync_env_file(
        p,
        catalog=cat,
        shell_env={"ANTHROPIC_API_KEY": "canonical", "CLAUDE_CONSOLE_API_KEY": "alias"},
    )
    after = parse_dotenv(p)
    assert after["ANTHROPIC_API_KEY"] == "canonical"


def test_sync_preserves_existing_secrets_and_user_values(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "JWT_SECRET=user-stable-secret\nINITIAL_PASSWORD=123456\nGROQ_API_KEY=manual\n",
        encoding="utf-8",
    )
    report = sync_env_file(
        p,
        catalog=_cat(),
        shell_env={"GROQ_API_KEY": "shell-overrides-me-NOT", "GEMINI_API_KEY": "gem"},
    )
    after = parse_dotenv(p)
    # Existing .env values are sacred
    assert after["JWT_SECRET"] == "user-stable-secret"
    assert after["INITIAL_PASSWORD"] == "123456"
    # Shell does NOT overwrite existing .env value
    assert after["GROQ_API_KEY"] == "manual"
    # Shell DOES fill empty slots
    assert after["GEMINI_API_KEY"] == "gem"
    assert "JWT_SECRET" in report.secrets_preserved
    # INITIAL_PASSWORD is user-managed, not in server-secret tracking; just
    # confirm the file kept it untouched.
    assert after["INITIAL_PASSWORD"] == "123456"
    # Secrets that weren't already set still get generated
    assert "API_KEY_SECRET" in report.secrets_generated


def test_sync_is_idempotent(tmp_path):
    p = tmp_path / ".env"
    sync_env_file(p, catalog=_cat(), shell_env={"GROQ_API_KEY": "k"})
    snap1 = p.read_text(encoding="utf-8")
    sync_env_file(p, catalog=_cat(), shell_env={"GROQ_API_KEY": "k"})
    snap2 = p.read_text(encoding="utf-8")
    assert snap1 == snap2, "second sync must not change anything"


def test_sync_seeded_secret_from_shell_is_preserved(tmp_path):
    p = tmp_path / ".env"
    report = sync_env_file(
        p,
        catalog=_cat(),
        shell_env={"JWT_SECRET": "ci-seeded", "GROQ_API_KEY": "k"},
    )
    after = parse_dotenv(p)
    assert after["JWT_SECRET"] == "ci-seeded"
    assert "JWT_SECRET" in report.secrets_preserved
