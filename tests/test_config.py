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
