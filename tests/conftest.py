import pytest

from offer_engine.config import ENV_KEYS

OPT_IN_MARKERS = ("live", "slow")


def pytest_collection_modifyitems(config, items):
    """Skip `live` and `slow` tests unless `-m` names the marker."""
    markexpr = config.getoption("markexpr") or ""
    for marker in OPT_IN_MARKERS:
        if marker in markexpr:
            continue
        skip = pytest.mark.skip(reason=f"{marker} test; run with -m {marker}")
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """No offer-engine keys in the process environment and a cwd with no `.env`."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path
