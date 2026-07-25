"""Authenticated Streamlit entrypoint with mandate-scoped compatibility adapters."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import streamlit as st

from api.config import ApiSettings
from security import (
    AuthenticationService,
    InvalidCredentialsError,
    SQLiteIdentityStore,
)


st.set_page_config(
    page_title="Capital Intelligence Platform",
    page_icon="📊",
    layout="wide",
)


@st.cache_resource
def authentication_service() -> AuthenticationService:
    settings = ApiSettings.from_env()
    service = AuthenticationService(
        SQLiteIdentityStore(
            settings.identity_database,
            access_ttl=timedelta(minutes=settings.access_token_minutes),
            refresh_ttl=timedelta(days=settings.refresh_token_days),
            password_minimum_length=settings.password_minimum_length,
        ),
        required=settings.authentication_required,
    )
    service.store.bootstrap_administrator(
        email=settings.bootstrap_admin_email,
        password=settings.bootstrap_admin_password,
        display_name=settings.bootstrap_admin_name,
    )
    return service


def _clear_session() -> None:
    st.session_state.pop("access_token", None)
    st.session_state.pop("refresh_token", None)


def _principal():
    service = authentication_service()
    if not service.required:
        return service.principal_for_access_token(None)
    access_token = st.session_state.get("access_token")
    if access_token:
        try:
            return service.principal_for_access_token(access_token)
        except InvalidCredentialsError:
            refresh_token = st.session_state.get("refresh_token")
            if refresh_token:
                try:
                    tokens = service.store.refresh(refresh_token)
                except InvalidCredentialsError:
                    _clear_session()
                else:
                    st.session_state.access_token = tokens.access_token
                    st.session_state.refresh_token = tokens.refresh_token
                    return service.principal_for_access_token(tokens.access_token)
            else:
                _clear_session()
    return None


def _login_screen() -> None:
    service = authentication_service()
    st.title("Capital Intelligence Platform")
    st.caption("Sign in to your authorized mandates and personal CIO memory.")
    if service.store.count_users() == 0:
        st.error(
            "No user accounts are configured. Set "
            "CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_EMAIL and "
            "CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_PASSWORD, then restart the app."
        )
        st.stop()
    with st.form("capital-intelligence-login"):
        email = st.text_input("Email address")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        try:
            tokens = service.store.login(email=email, password=password)
        except (InvalidCredentialsError, ValueError):
            st.error("The email address or password is incorrect.")
        else:
            st.session_state.access_token = tokens.access_token
            st.session_state.refresh_token = tokens.refresh_token
            st.rerun()
    st.stop()


def _install_scoped_adapters(principal) -> None:
    """Scope legacy Streamlit reads while the UI migrates to API clients."""

    import core.portfolio as portfolio_services
    import personalization

    original_get_mandates = portfolio_services.get_mandates
    original_get_details = portfolio_services.get_mandate_details
    original_get_trades = portfolio_services.get_trade_history
    original_memory_store = personalization.SQLiteInvestorMemoryStore

    def authorized_mandates() -> list[dict]:
        return [
            mandate
            for mandate in original_get_mandates()
            if principal.can_access_mandate(str(mandate["code"]))
        ]

    def authorized_details(mandate_code: str):
        if not principal.can_access_mandate(mandate_code):
            return None
        return original_get_details(mandate_code)

    def authorized_trades(
        mandate_code: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if mandate_code is not None:
            if not principal.can_access_mandate(mandate_code):
                return []
            return original_get_trades(mandate_code, limit=limit)
        items: list[dict] = []
        for mandate in authorized_mandates():
            items.extend(original_get_trades(str(mandate["code"]), limit=limit))
        items.sort(key=lambda item: int(item.get("id", 0)), reverse=True)
        return items[:limit]

    def authorized_totals() -> dict:
        mandates = authorized_mandates()
        starting = sum(float(item["starting_capital"]) for item in mandates)
        cash = sum(float(item["cash"]) for item in mandates)
        nav = sum(float(item["nav"]) for item in mandates)
        return {
            "mandate_count": len(mandates),
            "starting_capital": starting,
            "starting": starting,
            "cash": cash,
            "nav": nav,
            "total_return": ((nav / starting) - 1 if starting else 0.0),
        }

    investor_identifier = principal.investor_identifier or principal.user_id

    class AuthorizedMemoryStore(original_memory_store):
        def profile(self, ignored_identifier: str):
            del ignored_identifier
            return super().profile(investor_identifier)

        def events(self, ignored_identifier: str, *, limit: int = 100):
            del ignored_identifier
            return super().events(investor_identifier, limit=limit)

        def count(self, ignored_identifier: str | None = None):
            del ignored_identifier
            return super().count(investor_identifier)

        def append(self, event):
            if not principal.can_access_investor(investor_identifier, write=True):
                raise PermissionError("investor reflection access is not authorized")
            return super().append(
                replace(event, investor_identifier=investor_identifier)
            )

    portfolio_services.get_mandates = authorized_mandates
    portfolio_services.get_all_mandates = authorized_mandates
    portfolio_services.get_mandate_details = authorized_details
    portfolio_services.get_mandate = authorized_details
    portfolio_services.get_trade_history = authorized_trades
    portfolio_services.get_portfolio_totals = authorized_totals
    portfolio_services.portfolio_totals = authorized_totals
    personalization.SQLiteInvestorMemoryStore = AuthorizedMemoryStore


principal = _principal()
if principal is None:
    _login_screen()

with st.sidebar:
    st.caption(f"Signed in as **{principal.display_name}**")
    if st.button("Sign out"):
        token = st.session_state.get("access_token")
        if token:
            authentication_service().store.logout(token)
        _clear_session()
        st.rerun()

_install_scoped_adapters(principal)

# app.py owns the current product experience. Disable its second page-config call
# and execute it after authentication and data-scope adapters are installed.
_original_set_page_config = st.set_page_config
st.set_page_config = lambda **kwargs: None
try:
    source = Path("app.py").read_text(encoding="utf-8")
    exec(compile(source, "app.py", "exec"), {"__name__": "__main__"})
finally:
    st.set_page_config = _original_set_page_config
