#!/usr/bin/env python3
"""Read-only report of stored policies that the strict parser (ADR-0026) would
treat as malformed, or that exceed its limits. Run it BEFORE rolling out the
fail-closed policy gate, so no tenant is surprised by blocked tools.

    cd backend
    python scripts/policy_inventory.py            # human-readable
    python scripts/policy_inventory.py --json     # machine-readable

It never writes. It prints policy id, name, company id, size and the problems -
never the policy text. A listed policy fails closed at runtime (every tool call of
the personas it applies to is denied) until its executable ```policy / ```json /
```yaml blocks are fixed, or its prose is moved to a ```text fence.
Exit code 1 when at least one policy has problems.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from sqlmodel import select

    from database import get_session
    from models import Policy
    from services.policy_engine import validate_policy_content

    report = []
    with get_session() as session:
        for p in session.exec(select(Policy)).all():
            problems = validate_policy_content(p.content or "")
            if problems:
                report.append(
                    {
                        "policy_id": p.id,
                        "name": p.name,
                        "company_id": p.company_id,
                        "scope": p.scope,
                        "active": bool(p.is_active),
                        "bytes": len((p.content or "").encode("utf-8", "ignore")),
                        "problems": problems,
                    }
                )

    if args.json:
        print(json.dumps(report, indent=2))
    elif not report:
        print("All stored policies parse under the strict contract.")
    else:
        for r in report:
            flag = "ACTIVE" if r["active"] else "inactive"
            print(f"{r['policy_id']}  {flag:8}  {r['bytes']:>8} B  {r['name']}")
            for why in r["problems"]:
                print(f"    - {why}")
        print(f"\n{len(report)} policy(ies) would fail closed.")
    return 1 if report else 0


if __name__ == "__main__":
    raise SystemExit(main())
