"""Every mounted route must authenticate, unless it is on the public list.

A route added without a login dependency fails this test (the unauthenticated
/git and /audit routers were found by review, not by a test). The public list is
deliberate and short; adding to it needs a reason.
"""

from fastapi.routing import APIRoute

from api import auth as auth_mod
from api import deps

AUTH_DEPENDENCIES = {
    auth_mod.get_current_user,
    auth_mod.require_manager,
    auth_mod.require_founder,
    deps.get_persona_gateway,
    deps.get_persona_audit,
    deps.get_persona_exec,
}

# (method, path) that are public on purpose or authenticate by hand (credentials
# are verified inside the handler: OTP, refresh token, persona/web token, IdP).
PUBLIC = {
    ("POST", "/auth/token"),  # login
    ("GET", "/auth/setup-status"),  # first-run wizard
    ("POST", "/auth/setup"),  # first-run wizard (refuses once a user exists)
    ("GET", "/health"),
    ("GET", "/"),  # service banner
    ("GET", "/system/version"),
    ("GET", "/tenant/resolve"),  # branding for the login page
    ("GET", "/auth.md"),
    ("GET", "/.well-known/opencode"),
    ("GET", "/.well-known/opencode/pubkey"),
    ("GET", "/.well-known/api-catalog"),
    ("GET", "/.well-known/agent-card.json"),
}
MANUAL_AUTH = {
    ("POST", "/auth/demo/request-otp"),
    ("POST", "/auth/demo/verify-otp"),
    ("POST", "/workstation/persona-token/refresh"),  # refresh token
    ("POST", "/workstation/persona-token/revoke"),  # _persona_operator
    ("POST", "/workstation/commands"),  # _persona_operator
    ("POST", "/workstation/oidc/exchange"),  # IdP token
}


def _dependency_calls(dependant):
    seen = set()
    stack = [dependant]
    while stack:
        d = stack.pop()
        if d.call is not None:
            seen.add(d.call)
        stack.extend(d.dependencies)
    return seen


def test_every_route_authenticates_or_is_explicitly_public():
    from main import app

    missing = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        calls = _dependency_calls(route.dependant)
        if calls & AUTH_DEPENDENCIES:
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) in PUBLIC | MANUAL_AUTH:
                continue
            missing.append(f"{method} {route.path}")
    assert not missing, "routes without authentication: " + ", ".join(sorted(missing))
