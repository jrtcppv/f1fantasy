from datetime import date
from decimal import Decimal as D

import pytest

from f1fantasy.config import load_config
from f1fantasy.models import Asset, Dataset, FantasyScore, Price, Race


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def dataset():
    # Entirely synthetic. Deliberately not the user's illustrative asset data.
    races = [Race(f"2026:{n}", 2026, n, f"Test race {n}", date(2026, n, 1), n < 5, f"Circuit {n}") for n in range(1, 6)]
    assets = [Asset("2026:D", "SYN", "Synthetic Driver", "driver", True),
              Asset("2026:C", "SYC", "Synthetic Constructor", "constructor", True)]
    scores = [FantasyScore(a.id, races[i].id, D(p), "DNF" if p < 0 else "")
              for a in assets for i, p in enumerate((99, -25, 18, 20))]
    prices = [Price(a.id, r.id, D("8") if a.kind == "driver" else D("20")) for a in assets for r in races]
    return Dataset(races, assets, scores, prices, source="SYNTHETIC TEST DATA")
