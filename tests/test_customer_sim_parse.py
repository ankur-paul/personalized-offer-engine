import pytest

from offer_engine.customer_sim.app import parse_code


@pytest.mark.parametrize(
    ("caption", "code"),
    [
        ("Still thinking about those picks?\nCode: POE-DEMO01", "POE-DEMO01"),
        ("Use POE-7K3Q9X before Friday", "POE-7K3Q9X"),
        ("code: poe-demo01", "POE-DEMO01"),
        ("First POE-AAAAAA then POE-BBBBBB", "POE-AAAAAA"),
    ],
)
def test_code_is_parsed(caption, code):
    assert parse_code(caption) == code


@pytest.mark.parametrize("caption", [None, "", "No code here", "POE-SHORT", "POE-TOOLONG1", "XPOE-DEMO01"])
def test_no_code(caption):
    assert parse_code(caption) is None


def test_every_customer_bot_gets_its_own_app_and_no_key_means_no_agent():
    from offer_engine.config import Settings
    from offer_engine.customer_sim.app import agent_client, build_app

    settings = Settings(
        offer_bot_username="@poe_offer_bot", customer_bots=[("c1_bot", "111:a"), ("c2_bot", "222:b")]
    )
    apps = [build_app(settings, name, token, None) for name, token in settings.customer_bots]
    assert [app.bot.token for app in apps] == ["111:a", "222:b"]
    assert agent_client(settings) is None
