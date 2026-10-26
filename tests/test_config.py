from pathlib import Path

import pytest

from offer_engine.config import Settings, load_settings, parse_customer_bots


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, []),
        ("", []),
        ("   ", []),
        ("alice_bot:123:AAA", [("alice_bot", "123:AAA")]),
        (
            "alice_bot:111:AAA, bob_bot:222:BBB,carol_bot:333:CCC",
            [("alice_bot", "111:AAA"), ("bob_bot", "222:BBB"), ("carol_bot", "333:CCC")],
        ),
    ],
)
def test_parse_customer_bots(raw, expected):
    assert parse_customer_bots(raw) == expected


@pytest.mark.parametrize("raw", ["alice_bot", "alice_bot:", ":123:AAA", "alice_bot:111:AAA,,bob_bot:222:BBB"])
def test_parse_customer_bots_malformed_raises_clear_error(raw):
    with pytest.raises(ValueError, match="CUSTOMER_BOTS entry .* malformed; expected username:token"):
        parse_customer_bots(raw)


def test_malformed_error_does_not_echo_the_token():
    with pytest.raises(ValueError) as exc:
        parse_customer_bots("alice_bot:111:SECRET,bob_bot")
    assert "SECRET" not in str(exc.value)


def test_defaults_with_no_env(clean_env):
    settings = load_settings()
    assert settings == Settings()
    assert settings.db_path == Path("data/offer_engine.db")
    assert settings.seed == 7
    assert settings.customer_bots == []
    assert settings.console_password is None


def test_reads_env_file(clean_env):
    env_file = clean_env / "custom.env"
    env_file.write_text(
        "OFFER_BOT_TOKEN=111:AAA\n"
        "OFFER_BOT_USERNAME=poe_offer_bot\n"
        "CUSTOMER_BOTS=alice_bot:222:BBB\n"
        "ANTHROPIC_API_KEY=sk-test\n"
        "OFFER_AGENT_MODEL=model-a\n"
        "FAST_AGENT_MODEL=model-b\n"
        "DB_PATH=/tmp/x.db\n"
        "SEED=42\n"
        "CONSOLE_PASSWORD=pw\n"
        "AGENT_MODE=Replay\n"
        "DEMO_SEED=7\n"
    )
    settings = load_settings(env_file)
    assert settings == Settings(
        offer_bot_token="111:AAA",
        offer_bot_username="poe_offer_bot",
        customer_bots=[("alice_bot", "222:BBB")],
        anthropic_api_key="sk-test",
        offer_agent_model="model-a",
        fast_agent_model="model-b",
        db_path=Path("/tmp/x.db"),
        seed=42,
        console_password="pw",
        agent_mode="replay",
        demo_seed=7,
    )


def test_reads_dot_env_in_cwd_by_default(clean_env):
    (clean_env / ".env").write_text("OFFER_BOT_USERNAME=poe_offer_bot\n")
    assert load_settings().offer_bot_username == "poe_offer_bot"


def test_process_environment_overrides_file(clean_env, monkeypatch):
    (clean_env / ".env").write_text("SEED=1\n")
    monkeypatch.setenv("SEED", "2")
    assert load_settings().seed == 2


def test_empty_values_count_as_missing(clean_env):
    (clean_env / ".env").write_text("OFFER_BOT_TOKEN=\nSEED=\n")
    settings = load_settings()
    assert settings.offer_bot_token is None
    assert settings.seed == 7


def test_bad_seed_raises(clean_env):
    (clean_env / ".env").write_text("SEED=abc\n")
    with pytest.raises(ValueError, match="SEED must be an integer"):
        load_settings()


def test_settings_is_frozen():
    with pytest.raises(AttributeError):
        Settings().seed = 1


def test_bad_agent_mode_raises(clean_env):
    (clean_env / ".env").write_text("AGENT_MODE=sometimes\n")
    with pytest.raises(ValueError, match="AGENT_MODE must be one of live, replay, record"):
        load_settings()


def test_bad_demo_seed_raises(clean_env):
    (clean_env / ".env").write_text("DEMO_SEED=x\n")
    with pytest.raises(ValueError, match="DEMO_SEED must be an integer"):
        load_settings()


def test_env_file_is_parsed_once_until_it_changes(clean_env, monkeypatch):
    """The pipeline reads settings once per Decision; re-parsing `.env` each time was half the Daily Sweep."""
    import os

    from offer_engine import config

    env = clean_env / ".env"
    env.write_text("AGENT_MODE=live\n")
    parses = []
    real = config.dotenv_values
    monkeypatch.setattr(config, "dotenv_values", lambda path: parses.append(path) or real(path))
    for _ in range(3):
        assert load_settings().agent_mode == "live"
    assert len(parses) == 1

    env.write_text("AGENT_MODE=replay\n")
    stat = env.stat()
    os.utime(env, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert load_settings().agent_mode == "replay"
    assert len(parses) == 2


def test_removed_env_file_reads_as_empty(clean_env):
    env = clean_env / ".env"
    env.write_text("SEED=3\n")
    assert load_settings().seed == 3
    env.unlink()
    assert load_settings().seed == 7
