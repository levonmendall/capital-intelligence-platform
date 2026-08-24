from __future__ import annotations

from portfolio.constants import CANONICAL_PORTFOLIO_CODE
from render_app import _enable_public_streamlit_access
from security import AuthenticationService, SQLiteIdentityStore


def test_render_streamlit_disables_only_child_login_gate() -> None:
    parent_environment = {
        "CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED": "true",
    }
    streamlit_environment = dict(parent_environment)

    _enable_public_streamlit_access(streamlit_environment)

    assert parent_environment["CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED"] == "true"
    assert streamlit_environment["CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED"] == "false"


def test_public_render_principal_is_read_only(tmp_path) -> None:
    environment = {
        "CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED": "true",
    }
    _enable_public_streamlit_access(environment)
    authentication_required = (
        environment["CAPITAL_INTELLIGENCE_AUTHENTICATION_REQUIRED"].strip().lower()
        == "true"
    )
    service = AuthenticationService(
        SQLiteIdentityStore(tmp_path / "identity.db"),
        required=authentication_required,
    )

    principal = service.principal_for_access_token(None)

    assert principal.is_anonymous is True
    assert principal.is_administrator is False
    assert principal.can_access_mandate(CANONICAL_PORTFOLIO_CODE) is True
    assert principal.can_access_mandate(CANONICAL_PORTFOLIO_CODE, write=True) is False
