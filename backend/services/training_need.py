"""Training-need signals from fit ratings (ADR-0021 §6).

A signal says "here is where a person or a unit may need training or clearer rules".
It is not a score and never a disciplinary measure, and it is built to be read in this
order:

1. **The unit first.** When many people in a unit are `not_met` on the same criterion,
   the finding is that *the rule or its training is unclear* — it goes to whoever owns
   the rubric (a department head, executive or founder over that unit), with counts and
   no names.
2. **The person second, and to the person first.** A per-person signal needs enough rated
   work in the window and a not-met share above the company's bar. It is returned only in
   the person's own review (`GET /me`); nothing here shows it to a manager.

Only `live`, uncontested, *decided* ratings count (`met` / `not_met`). `shadow` ratings,
contested ones and `unclear` answers never do. The starting values (10 rated items in 30
days, a 50 % bar) are proposals; the company sets the bar and the minimum.
"""

from __future__ import annotations

from datetime import date

from sqlmodel import select

from models import Personnel, WorkRating, WorkTrainingShare
from services import work_review as wr

WINDOW_DAYS = 30
DEFAULT_MIN_RATED = 10
DEFAULT_BAR = 0.5
MIN_RATED_RANGE = (3, 200)
BAR_RANGE = (0.05, 1.0)


# ── the company's settings ────────────────────────────────────────────────────


def min_rated(session, company_id: str) -> int:
    try:
        n = int(wr._get(session, f"work_review.training.min_rated:{company_id}") or "")
    except ValueError:
        return DEFAULT_MIN_RATED
    lo, hi = MIN_RATED_RANGE
    return n if lo <= n <= hi else DEFAULT_MIN_RATED


def bar(session, company_id: str) -> float:
    try:
        b = float(wr._get(session, f"work_review.training.bar:{company_id}") or "")
    except ValueError:
        return DEFAULT_BAR
    lo, hi = BAR_RANGE
    return b if lo <= b <= hi else DEFAULT_BAR


def sharing_enabled(session, company_id: str) -> bool:
    """Whether people may choose to share a signal with their manager. Off by default: it
    needs a product and legal decision per company (ADR-0019 open question 4)."""
    v = wr._get(session, f"work_review.training.sharing:{company_id}")
    return v is not None and v.strip().lower() in wr._TRUE


def set_sharing_enabled(session, company_id: str, on: bool) -> None:
    wr._put(
        session, f"work_review.training.sharing:{company_id}", "true" if on else "false"
    )


def set_min_rated(session, company_id: str, n: int) -> None:
    wr._put(session, f"work_review.training.min_rated:{company_id}", str(int(n)))


def set_bar(session, company_id: str, b: float) -> None:
    wr._put(session, f"work_review.training.bar:{company_id}", repr(float(b)))


# ── counting ──────────────────────────────────────────────────────────────────


def _decided(session, person_ids: list[str], today: date | None) -> list[WorkRating]:
    first = wr._first_day(WINDOW_DAYS, today)
    rows = session.exec(
        select(WorkRating).where(
            WorkRating.personnel_id.in_(person_ids),
            WorkRating.day >= first,
            WorkRating.criterion_status == "live",
            WorkRating.verdict.in_(("met", "not_met")),
        )
    ).all()
    return [r for r in rows if not wr._open_contest(r)]


def person_signals(
    session, subject: Personnel, today: date | None = None
) -> list[dict]:
    """Criteria on which this person's decided, live ratings clear both thresholds."""
    cid = subject.company_id or ""
    need, threshold = min_rated(session, cid), bar(session, cid)
    tally: dict[tuple[str, str], list[int]] = {}
    for r in _decided(session, [subject.id], today):
        t = tally.setdefault((r.criterion_id, r.criterion_hash), [0, 0])
        t[0] += 1
        t[1] += r.verdict == "not_met"
    out = []
    for (crit, chash), (rated, not_met) in sorted(tally.items()):
        share = not_met / rated
        if rated >= need and share >= threshold:
            out.append(
                {
                    "criterion_id": crit,
                    "criterion_hash": chash,
                    "rated": rated,
                    "not_met": not_met,
                    "not_met_share": round(share, 2),
                    "window_days": WINDOW_DAYS,
                }
            )
    return out


def unit_findings(
    session, members: list[Personnel], today: date | None = None
) -> list[dict] | None:
    """Criteria on which a whole unit struggles, as counts with no names.

    None when the unit is smaller than the group floor (nothing may be said); otherwise a
    list (possibly empty). A criterion is a finding only if at least the floor of
    *different people* were rated on it and at least the floor of them had a not-met, in
    addition to the same rated-count and share thresholds as for a person — so a finding
    can never be traced to one or two individuals."""
    floor = wr.min_group()
    if len(members) < floor:
        return None
    cid = members[0].company_id or ""
    need, threshold = min_rated(session, cid), bar(session, cid)
    groups: dict[tuple[str, str], dict] = {}
    for r in _decided(session, [m.id for m in members], today):
        g = groups.setdefault(
            (r.criterion_id, r.criterion_hash),
            {"rated": 0, "not_met": 0, "people": set(), "people_not_met": set()},
        )
        g["rated"] += 1
        g["people"].add(r.personnel_id)
        if r.verdict == "not_met":
            g["not_met"] += 1
            g["people_not_met"].add(r.personnel_id)
    out = []
    for (crit, chash), g in sorted(groups.items()):
        share = g["not_met"] / g["rated"]
        if (
            g["rated"] >= need
            and share >= threshold
            and len(g["people"]) >= floor
            and len(g["people_not_met"]) >= floor
        ):
            out.append(
                {
                    "criterion_id": crit,
                    "criterion_hash": chash,
                    "rated": g["rated"],
                    "not_met": g["not_met"],
                    "not_met_share": round(share, 2),
                    "n_people": len(g["people"]),
                    "n_people_not_met": len(g["people_not_met"]),
                    "window_days": WINDOW_DAYS,
                    "reading": "rule_or_training_unclear",
                }
            )
    return out


def shared_signals(
    session, subject: Personnel, today: date | None = None
) -> list[dict]:
    """The signals this person chose to share with their direct manager — and only those
    that still hold today, and only while the company allows sharing. The share is
    consent, not data: a signal that has lapsed disappears from the manager's view."""
    cid = subject.company_id or ""
    if not sharing_enabled(session, cid):
        return []
    shared = {
        (r.criterion_id, r.criterion_hash)
        for r in session.exec(
            select(WorkTrainingShare).where(
                WorkTrainingShare.personnel_id == subject.id
            )
        ).all()
    }
    return [
        {**e, "kind": "support_requested"}
        for e in person_signals(session, subject, today)
        if (e["criterion_id"], e["criterion_hash"]) in shared
    ]


def team_findings(
    session, leader: Personnel, today: date | None = None
) -> tuple[int, list[dict] | None]:
    """The unit finding for a leader's own team (their direct reports): (people, findings),
    findings None when the team is below the group floor."""
    members = wr.direct_reports(session, leader)
    if not members:
        return 0, []
    return len(members), unit_findings(session, members, today)
