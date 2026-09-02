"""
Server-side revocation for persona tokens (ADR-0007).

Two mechanisms, both checked by the workstation auth deps (`api/deps.py`):

  - **per-jti** (`RevokedToken`): a specific token id is dead. Written when a
    refresh token is rotated (its old jti) or an operator kills one token.
  - **per-persona `not_before`** (`PersonaTokenState`): every token issued before
    a timestamp is dead — the "laptop lost" button, no jti needed.

All helpers are best-effort against the DB and fail **closed** on error (a
revocation check that cannot run rejects the token).
"""

from __future__ import annotations

from datetime import datetime

from database import get_session
from models import PersonaTokenState, RevokedToken


def is_revoked(
    jti: str | None, persona_id: str | None, issued_at: datetime | None
) -> bool:
    """True if this token must be rejected (jti blacklisted, or issued before the
    persona's not_before marker). Raises nothing — any failure returns True."""
    try:
        with get_session() as session:
            if jti and session.get(RevokedToken, jti) is not None:
                return True
            if persona_id:
                state = session.get(PersonaTokenState, persona_id)
                if state is not None and issued_at is not None:
                    # tokens issued at/after the marker survive
                    if issued_at < state.not_before:
                        return True
                # An issued_at we cannot compare against an existing marker is
                # treated as stale (fail closed).
                if state is not None and issued_at is None:
                    return True
        return False
    except Exception:
        return True


def revoke_jti(jti: str, persona_id: str, company_id: str | None, reason: str) -> None:
    with get_session() as session:
        if session.get(RevokedToken, jti) is None:
            session.add(
                RevokedToken(
                    jti=jti,
                    persona_id=persona_id,
                    company_id=company_id,
                    reason=reason,
                )
            )
            session.commit()


def revoke_all(persona_id: str, company_id: str | None, reason: str) -> datetime:
    """Set the persona's not_before marker to now — kills every existing token."""
    now = datetime.utcnow()
    with get_session() as session:
        state = session.get(PersonaTokenState, persona_id)
        if state is None:
            state = PersonaTokenState(
                persona_id=persona_id, company_id=company_id, not_before=now
            )
            session.add(state)
        else:
            state.not_before = now
            state.updated_at = now
            state.company_id = company_id or state.company_id
        session.commit()
    # No "un-revoke" needed: a fresh `3pa login` mints a token whose iat is after
    # the marker, so it passes without the marker being cleared.
    return now
