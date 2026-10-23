"""Both bot processes build offline. Handler behaviour is tested in test_responses.py and test_testers.py."""

from offer_engine.offer_bot import app as offer_bot_app


def test_handler_modules_all_register():
    for name in offer_bot_app.HANDLER_MODULES:
        assert callable(__import__(name, fromlist=["register"]).register)


def test_both_bots_build_their_handlers_offline():
    from offer_engine.config import Settings
    from offer_engine.customer_sim import app as customer_sim_app

    settings = Settings(
        offer_bot_token="123:fake",
        offer_bot_username="poe_offer_bot",
        customer_bots=[("poe_c1_bot", "456:fake")],
    )
    # testers: /start command and text, picks, /offers, /whoami, /switch; responses: buttons, /claim and /notnow, /stop.
    assert sum(len(group) for group in offer_bot_app.build_app(settings).handlers.values()) == 9
    customer_bot = customer_sim_app.build_app(settings, "poe_c1_bot", "456:fake", None)
    assert sum(len(group) for group in customer_bot.handlers.values()) == 2
