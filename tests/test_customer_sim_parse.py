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
