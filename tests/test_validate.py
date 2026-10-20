import numpy as np
import pandas as pd

import validate


def good_registry():
    return pd.DataFrame({
        "mall_id": ["a", "b"], "name": ["Alpha Mall", "Beta Plaza"],
        "lat": [1.30, 1.35], "lon": [103.80, 103.85],
        "postal_code": ["123456", None], "address": ["1 Road ALPHA MALL", "2 Road BETA PLAZA"],
    })


def test_good_registry_passes():
    errors, warnings = validate.validate_registry(good_registry())
    assert errors == [] and warnings == []


def test_registry_errors():
    df = good_registry()
    df.loc[0, "lat"] = 2.5                                    # outside Singapore
    assert any("outside Singapore" in e for e in validate.validate_registry(df)[0])
    df = good_registry()
    df.loc[1, ["lat", "lon"]] = df.loc[0, ["lat", "lon"]].values
    assert any("sharing exactly one coordinate" in e for e in validate.validate_registry(df)[0])
    df = good_registry()
    df.loc[0, "postal_code"] = "39393"                        # a lost leading zero
    assert any("6 digits" in e for e in validate.validate_registry(df)[0])
    df = good_registry()
    df.loc[1, "name"] = "Alpha Mall"
    assert any("duplicate name" in e for e in validate.validate_registry(df)[0])


def test_address_that_does_not_mention_the_mall_is_a_warning_not_an_error():
    df = good_registry()
    df.loc[0, "address"] = "30 DOVER AVENUE IMMANUEL CONGREGATION"
    errors, warnings = validate.validate_registry(df)
    assert errors == [] and warnings and "Alpha Mall" in warnings[0]


def good_scores(n=3):
    return pd.DataFrame({"A_dining_score": [0.0, 50.0, 100.0][:n], "engagement_gap_score": [10.0, np.nan, 90.0][:n],
                         "A_dining_count": [0, 5, 9][:n]})


def test_scores_pass_and_allow_a_few_na_engagement_gaps():
    n = 40
    df = pd.DataFrame({"A_dining_score": np.linspace(0, 100, n), "engagement_gap_score": np.linspace(0, 100, n),
                       "A_dining_count": np.arange(n)})
    df.loc[0, "engagement_gap_score"] = np.nan                  # one mall with no residents nearby is fine
    assert validate.validate_scores(df, n)[0] == []
    df.loc[:9, "engagement_gap_score"] = np.nan                 # a quarter n/a means a broken join
    assert any("n/a for" in e for e in validate.validate_scores(df, n)[0])


def test_scores_errors():
    assert validate.validate_scores(good_scores(2), 3)[0]                       # row count mismatch
    df = good_scores(); df.loc[0, "A_dining_score"] = 140
    assert any("outside 0-100" in e for e in validate.validate_scores(df, 3)[0])
    df = good_scores(); df.loc[0, "A_dining_score"] = np.nan
    assert any("missing values" in e for e in validate.validate_scores(df, 3)[0])
    df = good_scores(); df.loc[0, "A_dining_count"] = -1
    assert any("negative counts" in e for e in validate.validate_scores(df, 3)[0])


def test_a_constant_score_column_is_flagged():
    df = good_scores().assign(B_fitness_score=0.0)
    assert any("constant" in w for w in validate.validate_scores(df, 3)[1])


def test_index_errors():
    idx = pd.DataFrame({"rank": [1, 2, 2], "tier": ["Gold"] * 3, "hpm_index": [3.0, 2.0, 1.0]})
    assert validate.validate_index(idx)[0]
    ok = pd.DataFrame({"rank": [1, 2, 3], "tier": ["Gold"] * 3, "hpm_index": [3.0, 2.0, 1.0]})
    assert validate.validate_index(ok)[0] == []


def test_enforce_raises_on_errors_and_not_on_warnings(capsys):
    validate.enforce("x", [], ["just a warning"])
    assert "just a warning" in capsys.readouterr().out
    try:
        validate.enforce("x", ["boom"], [])
    except ValueError as exc:
        assert "boom" in str(exc)
    else:
        raise AssertionError("expected ValueError")
