import subprocess
import sys

from offer_engine.cli import main

FULL_ENV = (
    "OFFER_BOT_TOKEN=111:TOKEN_OFFER_SECRET\n"
    "OFFER_BOT_USERNAME=poe_offer_bot\n"
    "CUSTOMER_BOTS=alice_bot:222:TOKEN_ALICE_SECRET\n"
    "ANTHROPIC_API_KEY=sk-ant-KEY_SECRET\n"
    "CONSOLE_PASSWORD=PASSWORD_SECRET\n"
)


def test_all_required_set_exits_zero(clean_env, capsys):
    (clean_env / ".env").write_text(FULL_ENV)
    assert main(["check-env"]) == 0
    out = capsys.readouterr().out
    assert "OFFER_BOT_TOKEN" in out
    assert "OFFER_AGENT_MODEL" in out and "missing" in out


def test_missing_required_key_exits_one(clean_env, capsys):
    (clean_env / ".env").write_text(FULL_ENV.replace("ANTHROPIC_API_KEY=sk-ant-KEY_SECRET\n", ""))
    assert main(["check-env"]) == 1
    line = next(l for l in capsys.readouterr().out.splitlines() if l.startswith("ANTHROPIC_API_KEY"))
    assert "missing" in line


def test_no_env_file_lists_everything_missing(clean_env, capsys):
    assert main(["check-env"]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines and all(line.split()[1] == "missing" for line in lines)


def test_output_never_contains_secret_values(clean_env, capsys):
    (clean_env / ".env").write_text(FULL_ENV)
    main(["check-env"])
    out = capsys.readouterr().out
    for secret in ("SECRET", "111:", "222:", "sk-ant", "poe_offer_bot", "alice_bot"):
        assert secret not in out


def test_malformed_customer_bots_exits_one_without_leaking(clean_env, capsys):
    (clean_env / ".env").write_text(FULL_ENV + "CUSTOMER_BOTS=alice_bot:222:TOKEN_ALICE_SECRET,broken\n")
    assert main(["check-env"]) == 1
    out = capsys.readouterr().out
    assert "malformed" in out
    assert "SECRET" not in out


def test_installed_script_runs(clean_env):
    result = subprocess.run(
        [sys.executable, "-m", "offer_engine", "check-env"], check=False, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "OFFER_BOT_TOKEN" in result.stdout
