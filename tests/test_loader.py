import pytest

from dcf_engine.loader import ModelError, load_model, parse_model


def test_scalars_expand_to_projection_years(simple_model):
    op = simple_model.primary.operating
    assert op.revenue_growth == (0.10, 0.10, 0.10)
    assert simple_model.projection_years == 3
    assert simple_model.projection_year_labels == (2026, 2027, 2028)


def test_defaults(simple_model):
    assert simple_model.company.currency == "USD"
    assert simple_model.company.illustrative is True
    assert simple_model.sensitivity.size == 5
    assert simple_model.current_share_price is None
    assert [s.name for s in simple_model.scenarios] == ["base"]


def test_scenarios_deep_merge_and_order(simple_raw):
    simple_raw["scenarios"] = {
        "bull": {"revenue_growth": 0.15, "terminal": {"exit_multiple": 10.0}},
        "bear": {"wacc": {"beta": 1.4}},
    }
    m = parse_model(simple_raw)
    assert [s.name for s in m.scenarios] == ["bear", "base", "bull"]
    bull, bear = m.scenario("bull"), m.scenario("bear")
    assert bull.operating.revenue_growth == (0.15,) * 3
    assert bull.terminal.exit_multiple == 10.0
    assert bull.terminal.growth_rate == 0.02  # inherited from base
    assert bear.capital.beta == 1.4
    assert bear.capital.risk_free_rate == 0.04  # inherited from base
    assert m.primary.name == "base"


def test_scenario_can_switch_to_unlevered_beta(simple_raw):
    simple_raw["scenarios"] = {"bear": {"wacc": {"unlevered_beta": 0.8}}}
    bear = parse_model(simple_raw).scenario("bear")
    assert bear.capital.beta == 0.8
    assert bear.capital.beta_is_unlevered


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r["assumptions"].update(revenue_growth=[0.1, 0.1]), "expected 3 values"),
        (lambda r: r["assumptions"].update(tax_rate=1.2), r"tax_rate: must be in \[0, 1\)"),
        (lambda r: r["financials"].update(diluted_shares=0), "must be positive"),
        (lambda r: r["financials"].pop("revenue"), r"financials\.revenue: required"),
        (lambda r: r["assumptions"]["wacc"].update(unlevered_beta=0.9), "exactly one of"),
        (lambda r: r["assumptions"].update(ebitda_margin="high"), "expected a number"),
        (lambda r: r["settings"].update(primary_scenario="bull"), "primary_scenario"),
        (lambda r: r["company"].pop("ticker"), r"company\.ticker"),
        (lambda r: r.pop("assumptions"), "assumptions: expected a mapping"),
    ],
)
def test_validation_errors(simple_raw, mutate, message):
    mutate(simple_raw)
    with pytest.raises(ModelError, match=message):
        parse_model(simple_raw)


def test_scenario_error_paths_name_the_scenario(simple_raw):
    simple_raw["scenarios"] = {"bear": {"revenue_growth": [0.1]}}
    with pytest.raises(ModelError, match=r"scenarios\.bear\.revenue_growth"):
        parse_model(simple_raw)


def test_missing_file(tmp_path):
    with pytest.raises(ModelError, match="not found"):
        load_model(tmp_path / "nope.yaml")


def test_invalid_yaml(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("company: [unclosed")
    with pytest.raises(ModelError, match="invalid YAML"):
        load_model(bad)


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("bear", "Bear case"),
        ("management_case", "Management case"),
        ("low-rates", "Low rates case"),
    ],
)
def test_scenario_labels(simple_raw, name, label):
    simple_raw["scenarios"] = {name: {}}
    assert parse_model(simple_raw).scenario(name).label == label
