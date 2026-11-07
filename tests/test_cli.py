from openpyxl import load_workbook

from dcf_engine.cli import main


def test_value_prints_summary_and_writes_workbook(examples_dir, tmp_path, capsys):
    out = tmp_path / "acme.xlsx"
    assert main(["value", str(examples_dir / "acme.yaml"), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Acme Robotics Inc. (ACME)" in text
    assert "Illustrative model of a fictional company" in text
    assert "Bear case   Base case   Bull case" in text
    assert "Implied share price: WACC vs. terminal growth (Base case)" in text
    assert f"Wrote {out}" in text
    assert load_workbook(out).sheetnames[0] == "Summary"


def test_scenario_flag_changes_primary_case(examples_dir, capsys):
    assert main(["value", str(examples_dir / "acme.yaml"), "--scenario", "bull"]) == 0
    text = capsys.readouterr().out
    assert "Free cash flow, bull case" in text
    assert "WACC vs. exit multiple (Bull case)" in text


def test_quiet_only_reports_the_file(examples_dir, tmp_path, capsys):
    out = tmp_path / "h.xlsx"
    assert main(["value", str(examples_dir / "harborview_foods.yaml"), "-q", "-o", str(out)]) == 0
    assert capsys.readouterr().out == f"Wrote {out}\n"


def test_validate(examples_dir, capsys):
    assert main(["validate", str(examples_dir / "cobalt_cloud.yaml")]) == 0
    assert "OK (3 scenario(s): bear, base, bull; 7-year projection)" in capsys.readouterr().out


def test_errors_exit_2_with_message(examples_dir, tmp_path, capsys):
    assert main(["value", str(tmp_path / "missing.yaml")]) == 2
    assert "model file not found" in capsys.readouterr().err

    assert main(["value", str(examples_dir / "acme.yaml"), "-s", "nope"]) == 2
    assert "unknown scenario 'nope'" in capsys.readouterr().err

    assert main(["value", str(examples_dir / "acme.yaml"), "-o", str(tmp_path / "x.csv")]) == 2
    captured = capsys.readouterr()
    assert "--out must be an .xlsx path" in captured.err
    assert captured.out == ""  # rejected before any work is printed


def test_undefined_perpetuity_is_reported(simple_raw, tmp_path, capsys):
    import yaml

    simple_raw["assumptions"]["terminal"]["growth_rate"] = 0.12
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(simple_raw))
    assert main(["value", str(path)]) == 2
    assert "must exceed terminal growth" in capsys.readouterr().err
