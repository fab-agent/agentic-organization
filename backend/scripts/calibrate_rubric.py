#!/usr/bin/env python3
"""Calibrate one rubric criterion against labelled examples (ADR-0021 §5).

    cd backend
    TYPESAFE_API_KEY=...  python scripts/calibrate_rubric.py \\
        --company <company id> --samples samples.yaml [--save]

`samples.yaml` names one criterion and lists work summaries labelled by its author:

    criterion: G1-revenue
    examples:
      - {text: "Built the renewal forecast for the top 20 accounts.", expected: met}
      - {text: "Reformatted the office seating plan.", expected: not_met}

The texts are redacted, as in production, before they go to the scoring model, but
they are still sent to it: use real or realistic summaries only if your company has
enabled that. The report prints counts and per-example verdicts, never the texts.
With `--save` a passing result is recorded for the criterion's current wording, which
is what lets the rubric file move it from `draft` to `shadow`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import get_session  # noqa: E402
from services import calibration as cal  # noqa: E402
from services.rating import get_rater  # noqa: E402


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--company", required=True)
    ap.add_argument("--samples", required=True, type=Path)
    ap.add_argument(
        "--save", action="store_true", help="record the result (a fail is recorded too)"
    )
    args = ap.parse_args(argv)

    if not os.getenv("TYPESAFE_API_KEY"):
        print("TYPESAFE_API_KEY is not set.", file=sys.stderr)
        return 2
    rater = get_rater()
    if rater is None:
        print("The scoring SDK is not available.", file=sys.stderr)
        return 2
    try:
        text = args.samples.read_text(encoding="utf-8")
        with get_session() as session:
            report = cal.run(session, args.company, text, rater, save=args.save)
            if args.save:
                session.commit()
    except (OSError, cal.CalibrationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    if report.errors:
        print(
            f"{report.errors} answer(s) failed and were counted as unclear "
            "(check the network policy and the key).",
            file=sys.stderr,
        )
    return 0 if report.passes else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
