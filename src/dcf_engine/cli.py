"""Command-line interface: ``dcf value`` and ``dcf validate``."""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections.abc import Sequence
from pathlib import Path

from dcf_engine import __version__
from dcf_engine.excel import write_workbook
from dcf_engine.loader import ModelError, load_model
from dcf_engine.model import CompanyModel
from dcf_engine.report import render
from dcf_engine.valuation import ValuationError, value_model


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dcf",
        description="Discounted cash flow valuation that writes a live-formula Excel model.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    value = sub.add_parser("value", help="value a company and optionally write the workbook")
    value.add_argument("model", type=Path, help="path to a company model YAML file")
    value.add_argument("-o", "--out", type=Path, help="write the Excel model to this .xlsx path")
    value.add_argument(
        "-s",
        "--scenario",
        help="scenario shown in the FCF table and used for the sensitivity grids "
        "(default: settings.primary_scenario, usually 'base')",
    )
    value.add_argument("-q", "--quiet", action="store_true", help="suppress the console summary")

    validate = sub.add_parser("validate", help="check a model file without writing anything")
    validate.add_argument("model", type=Path)
    return parser


def _with_primary(model: CompanyModel, scenario: str | None) -> CompanyModel:
    if scenario is None:
        return model
    names = [s.name for s in model.scenarios]
    if scenario not in names:
        raise ModelError(f"unknown scenario {scenario!r}; choose from {', '.join(names)}")
    return dataclasses.replace(model, primary_scenario=scenario)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        model = load_model(args.model)
        if args.command == "validate":
            result = value_model(model)
            print(
                f"{args.model}: OK ({len(model.scenarios)} scenario(s): "
                f"{', '.join(s.name for s in model.scenarios)}; "
                f"{model.projection_years}-year projection)"
            )
            return 0

        model = _with_primary(model, args.scenario)
        result = value_model(model)
        if not args.quiet:
            sys.stdout.write(render(result))
        if args.out:
            if args.out.suffix.lower() != ".xlsx":
                raise ModelError(f"--out must be an .xlsx path, got {args.out}")
            write_workbook(result, args.out)
            if not args.quiet:
                print()
            print(f"Wrote {args.out}")
    except (ModelError, ValuationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
