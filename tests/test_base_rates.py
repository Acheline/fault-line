from core.config import PLACEHOLDER, cfg
from risk import base_rates as br


def test_base_rates_computed_from_cache():
    out = br.compute(offline=True)
    assert out["values"]["exploit"]["status"] == "computed"
    assert out["values"]["loss_given_exploit"]["status"] == "computed"
    assert out["values"]["depeg_3pct_24h_annual_usde"]["status"] == "computed"
    p, bucket = br.exploit_p(out["detail"]["exploit"], "Lending", 1.6e9, 5e9)
    assert 0 < p < 0.5 and bucket.endswith(">=1B")


def test_fallback_is_flagged(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("fetch failed")
    monkeypatch.setattr(br, "depeg_rates", boom)
    out = br.compute(offline=True)
    v = out["values"]["depeg_3pct_24h_annual_synthetic"]
    assert v["status"] == PLACEHOLDER and v["value"] == cfg()["fallback_priors"]["depeg_3pct_24h_annual_synthetic"]
