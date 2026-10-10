from core.config import SOURCE, assumptions, cfg


def test_every_value_tagged_and_numeric_ones_have_sliders():
    a = assumptions()
    assert a and all(x.source == SOURCE for x in a)
    assert all(x.slider for x in a if x.numeric)
    assert {x.key for x in a if x.placeholder_prior} == {k for k in (x.key for x in a) if k.startswith("fallback_priors.")}


def test_values_match_answers_and_override():
    c = cfg()
    assert c["risk"]["lambda"] == 0.5 and c["sizing"]["ticket_usd"] == 5_000_000
    assert cfg({"risk.lambda": 1.0})["risk"]["lambda"] == 1.0
