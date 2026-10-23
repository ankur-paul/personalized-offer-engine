import os
import stat
from pathlib import Path

import pytest
from dotenv import dotenv_values
from telegram.error import InvalidToken, NetworkError

from offer_engine import setup_wizard
from offer_engine.cli import main
from offer_engine.config import parse_customer_bots
from offer_engine.setup_wizard import check_token, merge_env, run_wizard

OFFER_TOKEN = "111111:OFFER_TOKEN_SECRET_aaaaaaaaaaaaaaaaaaaa"
API_KEY = "sk-ant-API_KEY_SECRET"
BAD_TOKEN = "999999:BAD_TOKEN_SECRET_bbbbbbbbbbbbbbbbbbbbbb"
# Read at import, before `clean_env` clears the environment and leaves the repo.
LIVE_OFFER_TOKEN = os.environ.get("OFFER_BOT_TOKEN") or dotenv_values(Path(__file__).parents[1] / ".env").get(
    "OFFER_BOT_TOKEN"
)


def customer_token(n: int) -> str:
    return f"22222{n}:CUSTOMER_TOKEN_SECRET_{n}_cccccccccccccccccc"


# Tokens the fake getMe accepts, mapped to the bot username it returns.
KNOWN_BOTS = {OFFER_TOKEN: "poe_offer_bot"} | {customer_token(n): f"customer{n}_bot" for n in range(1, 9)}


class ScriptedIO:
    """Plays back answers in order; runs out with EOFError so a re-ask loop can't hang a test."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.transcript = []
        self.secret_prompts = []

    def say(self, text=""):
        self.transcript.append(text)

    def ask(self, prompt):
        self.transcript.append(prompt)
        return self._next()

    def ask_secret(self, prompt):
        self.transcript.append(prompt)
        self.secret_prompts.append(prompt)
        return self._next()

    def _next(self):
        if not self.answers:
            raise EOFError("script ran out of answers")
        return self.answers.pop(0)

    @property
    def text(self):
        return "\n".join(self.transcript)


@pytest.fixture(autouse=True)
def _isolated(clean_env):
    """check-env inside the wizard reads the process environment too; keep the developer's keys out of it."""


@pytest.fixture
def fake_getme(monkeypatch):
    calls = []

    def fake(token):
        calls.append(token)
        return KNOWN_BOTS.get(token)

    monkeypatch.setattr(setup_wizard, "check_token", fake)
    return calls


def fresh_run_answers(customer_count=7):
    answers = [OFFER_TOKEN, ""]  # token, Enter after the Bot-to-Bot screen
    answers.append("" if customer_count == 7 else str(customer_count))
    for n in range(1, customer_count + 1):
        answers += [customer_token(n), ""]
    answers += [API_KEY, "model-offer", "model-fast"]
    return answers


def assert_no_secrets(text):
    for secret in ("SECRET", "111111:", "22222", "sk-ant"):
        assert secret not in text


# merge_env


def test_merge_env_keeps_unrelated_lines_comments_and_order(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# header\nSEED=3\n\n# the bot\nOFFER_BOT_TOKEN=old\nexport DB_PATH=x.db\nCONSOLE_PASSWORD=\n"
    )
    merge_env(env, {"OFFER_BOT_TOKEN": "new", "CONSOLE_PASSWORD": "pw", "FAST_AGENT_MODEL": "m"})
    assert env.read_text() == (
        "# header\nSEED=3\n\n# the bot\nOFFER_BOT_TOKEN=new\nexport DB_PATH=x.db\nCONSOLE_PASSWORD=pw\n"
        "FAST_AGENT_MODEL=m\n"
    )


def test_merge_env_creates_file_with_mode_0600(tmp_path):
    env = tmp_path / ".env"
    merge_env(env, {"SEED": "1"})
    assert env.read_text() == "SEED=1\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_merge_env_tightens_an_open_file_to_0600(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SEED=1\n")
    os.chmod(env, 0o644)
    merge_env(env, {"SEED": "2"})
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_merge_env_replaces_every_copy_of_a_duplicated_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SEED=1\nSEED=2\n")
    merge_env(env, {"SEED": "3"})
    assert dotenv_values(env) == {"SEED": "3"}


@pytest.mark.parametrize("value", ["a b", "has # hash", "it's", 'say "hi"', "back\\slash", ""])
def test_merge_env_values_read_back_unchanged(tmp_path, value):
    env = tmp_path / ".env"
    merge_env(env, {"CONSOLE_PASSWORD": value})
    assert dotenv_values(env)["CONSOLE_PASSWORD"] == value


def test_merge_env_rejects_multiline_values(tmp_path):
    with pytest.raises(ValueError, match="single line"):
        merge_env(tmp_path / ".env", {"SEED": "1\nOFFER_BOT_TOKEN=x"})


def test_merge_env_leaves_no_temp_files(tmp_path):
    merge_env(tmp_path / ".env", {"SEED": "1"})
    assert [p.name for p in tmp_path.iterdir()] == [".env"]


# run_wizard


def test_fresh_run_writes_every_key(tmp_path, fake_getme):
    env = tmp_path / ".env"
    io = ScriptedIO(fresh_run_answers())
    run_wizard(io, env)

    values = dotenv_values(env)
    assert values["OFFER_BOT_TOKEN"] == OFFER_TOKEN
    assert values["OFFER_BOT_USERNAME"] == "poe_offer_bot"
    assert parse_customer_bots(values["CUSTOMER_BOTS"]) == [
        (f"customer{n}_bot", customer_token(n)) for n in range(1, 8)
    ]
    assert values["ANTHROPIC_API_KEY"] == API_KEY
    assert values["OFFER_AGENT_MODEL"] == "model-offer"
    assert values["FAST_AGENT_MODEL"] == "model-fast"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert io.answers == []
    assert "Setup complete" in io.text


def test_walks_all_five_steps_and_ends_with_check_env(tmp_path, fake_getme):
    io = ScriptedIO(fresh_run_answers())
    run_wizard(io, tmp_path / ".env")
    for step in range(1, 6):
        assert f"Step {step} of 5" in io.text
    assert any(line.split() == ["OFFER_BOT_TOKEN", "set"] for line in io.transcript)
    assert "Bot-to-Bot Communication Mode" in io.text


def test_tokens_and_key_are_asked_hidden(tmp_path, fake_getme):
    io = ScriptedIO(fresh_run_answers())
    run_wizard(io, tmp_path / ".env")
    assert len(io.secret_prompts) == 1 + 7 + 1


def test_output_never_contains_a_token_or_key(tmp_path, fake_getme):
    io = ScriptedIO([BAD_TOKEN] + fresh_run_answers())
    run_wizard(io, tmp_path / ".env")
    assert_no_secrets(io.text)


def test_bad_token_is_asked_again(tmp_path, fake_getme):
    io = ScriptedIO([BAD_TOKEN, ""] + fresh_run_answers())  # a rejected token, then an empty paste
    run_wizard(io, tmp_path / ".env")
    assert fake_getme[:2] == [BAD_TOKEN, OFFER_TOKEN]
    assert "did not accept that token" in io.text
    assert dotenv_values(tmp_path / ".env")["OFFER_BOT_TOKEN"] == OFFER_TOKEN


def test_reused_token_is_refused_without_calling_telegram(tmp_path, fake_getme):
    answers = fresh_run_answers()
    first_customer = answers.index(customer_token(1))
    answers.insert(first_customer, OFFER_TOKEN)
    io = ScriptedIO(answers)
    run_wizard(io, tmp_path / ".env")
    assert fake_getme.count(OFFER_TOKEN) == 1
    assert "already set up here" in io.text


@pytest.mark.parametrize("count", [6, 8])
def test_customer_bot_count_is_respected(tmp_path, fake_getme, count):
    run_wizard(ScriptedIO(fresh_run_answers(count)), tmp_path / ".env")
    assert len(parse_customer_bots(dotenv_values(tmp_path / ".env")["CUSTOMER_BOTS"])) == count


def test_customer_bot_count_outside_6_to_8_is_asked_again(tmp_path, fake_getme):
    answers = fresh_run_answers()
    count_at = answers.index(customer_token(1)) - 1
    answers[count_at:count_at] = ["5", "9", "seven"]
    io = ScriptedIO(answers)
    run_wizard(io, tmp_path / ".env")
    assert io.text.count("Enter a whole number from 6 to 8") == 3


def test_empty_model_answer_is_asked_again_when_nothing_is_set(tmp_path, fake_getme):
    answers = fresh_run_answers()
    answers[-2:-1] = ["", "model-offer"]
    io = ScriptedIO(answers)
    run_wizard(io, tmp_path / ".env")
    assert "OFFER_AGENT_MODEL is needed" in io.text
    assert dotenv_values(tmp_path / ".env")["OFFER_AGENT_MODEL"] == "model-offer"


def test_rerun_keeps_existing_values_and_lines(tmp_path, fake_getme):
    env = tmp_path / ".env"
    run_wizard(ScriptedIO(fresh_run_answers()), env)
    with env.open("a") as file:
        file.write("# my note\nSEED=11\n")
    before = env.read_text()
    fake_getme.clear()

    # keep Offer Bot, Enter on Bot-to-Bot, keep Customer Bots, keep key, Enter on both models
    io = ScriptedIO(["", "", "", "", "", ""])
    run_wizard(io, env)
    assert env.read_text() == before
    assert fake_getme == []
    assert io.secret_prompts == []
    assert_no_secrets(io.text)


def test_rerun_can_replace_a_value(tmp_path, fake_getme):
    env = tmp_path / ".env"
    run_wizard(ScriptedIO(fresh_run_answers()), env)
    io = ScriptedIO(["", "", "", "n", "sk-ant-NEW_SECRET", "claude-new", ""])
    run_wizard(io, env)
    values = dotenv_values(env)
    assert values["ANTHROPIC_API_KEY"] == "sk-ant-NEW_SECRET"
    assert values["OFFER_AGENT_MODEL"] == "claude-new"
    assert values["FAST_AGENT_MODEL"] == "model-fast"
    assert values["OFFER_BOT_TOKEN"] == OFFER_TOKEN


def test_stopped_run_keeps_finished_bots_and_resumes(tmp_path, fake_getme):
    env = tmp_path / ".env"
    answers = fresh_run_answers()
    stop_at = answers.index(customer_token(4))
    with pytest.raises(EOFError):
        run_wizard(ScriptedIO(answers[:stop_at]), env)
    assert len(parse_customer_bots(dotenv_values(env)["CUSTOMER_BOTS"])) == 3

    # keep Offer Bot, Enter on Bot-to-Bot, keep the 3 Customer Bots, default count 7, then bots 4-7
    resume = ["", "", "", ""]
    for n in range(4, 8):
        resume += [customer_token(n), ""]
    resume += [API_KEY, "model-offer", "model-fast"]
    io = ScriptedIO(resume)
    run_wizard(io, env)
    assert [u for u, _ in parse_customer_bots(dotenv_values(env)["CUSTOMER_BOTS"])] == [
        f"customer{n}_bot" for n in range(1, 8)
    ]
    assert io.answers == []


def test_malformed_customer_bots_are_set_up_again(tmp_path, fake_getme):
    env = tmp_path / ".env"
    env.write_text("CUSTOMER_BOTS=broken\n")
    answers = fresh_run_answers()
    io = ScriptedIO(answers)
    run_wizard(io, env)
    assert "malformed" in io.text
    assert len(parse_customer_bots(dotenv_values(env)["CUSTOMER_BOTS"])) == 7


def test_starts_from_env_example_when_there_is_no_env(tmp_path, fake_getme):
    (tmp_path / ".env.example").write_text("# Offer Bot token\nOFFER_BOT_TOKEN=\n# Seed\nSEED=\n")
    run_wizard(ScriptedIO(fresh_run_answers()), tmp_path / ".env")
    text = (tmp_path / ".env").read_text()
    assert text.startswith(f"# Offer Bot token\nOFFER_BOT_TOKEN={OFFER_TOKEN}\n# Seed\nSEED=\n")
    assert (tmp_path / ".env.example").read_text() == "# Offer Bot token\nOFFER_BOT_TOKEN=\n# Seed\nSEED=\n"


# check_token


class FakeBot:
    """Stands in for telegram.Bot: `async with`, then `get_me()`."""

    def __init__(self, token, error=None):
        self.error = error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_me(self):
        class Me:
            username = "poe_offer_bot"

        return Me()


def test_check_token_returns_username(monkeypatch):
    monkeypatch.setattr(setup_wizard, "Bot", FakeBot)
    assert check_token(OFFER_TOKEN) == "poe_offer_bot"


@pytest.mark.parametrize("error", [InvalidToken("Unauthorized"), NetworkError("offline")])
def test_check_token_returns_none_when_telegram_refuses_or_is_unreachable(monkeypatch, error):
    monkeypatch.setattr(setup_wizard, "Bot", lambda token: FakeBot(token, error))
    assert check_token(OFFER_TOKEN) is None


@pytest.mark.parametrize(
    "token", ["", "abc", "123:short", "123:has spaces in it aaaaaaaaaaaaaaaaa", "x" + OFFER_TOKEN]
)
def test_check_token_rejects_malformed_tokens_without_calling_telegram(monkeypatch, token):
    def no_network(_token):
        raise AssertionError("Telegram must not be called for a malformed token")

    monkeypatch.setattr(setup_wizard, "Bot", no_network)
    assert check_token(token) is None


@pytest.mark.live
def test_check_token_live():
    if not LIVE_OFFER_TOKEN:
        pytest.skip("needs OFFER_BOT_TOKEN in the environment or .env")
    assert check_token(LIVE_OFFER_TOKEN)
    assert check_token(BAD_TOKEN) is None


# command


def test_setup_is_listed_in_help(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "setup" in capsys.readouterr().out


def test_ctrl_c_stops_cleanly(monkeypatch, tmp_path, capsys):
    def interrupted(io, env_path):
        raise KeyboardInterrupt

    monkeypatch.setattr(setup_wizard, "run_wizard", interrupted)
    assert main(["setup", "--env-file", str(tmp_path / ".env")]) == 130
    assert "run `offer-engine setup` again" in capsys.readouterr().out
