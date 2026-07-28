"""Authenticated Streamlit entrypoint with per-session authorization adapters."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import streamlit as st

from api.config import ApiSettings
from core import portfolio as portfolio_services
from portfolio.constants import CANONICAL_PORTFOLIO_CODE
from delivery import (
    AlertChannel,
    AlertTopic,
    DeliveryPreference,
    DeliveryStatus,
    SQLiteAlertStore,
)
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
def runtime_settings() -> ApiSettings:
    return ApiSettings.from_env()


@st.cache_resource
def authentication_service() -> AuthenticationService:
    settings = runtime_settings()
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


@st.cache_resource
def alert_store() -> SQLiteAlertStore:
    settings = runtime_settings()
    path = settings.alert_database or settings.snapshot_database.with_name(
        "alerts.db"
    )
    return SQLiteAlertStore(path)


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
    st.caption("Sign in to authorized portfolios and CIO decision history.")
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


def _render_alert_controls(principal) -> None:
    store = alert_store()
    settings = runtime_settings()
    preference = store.get_preference(
        principal.user_id,
        fallback_email=principal.email,
    )
    unread = store.unread_count(principal.user_id)
    with st.expander(f"Notifications ({unread} unread)"):
        deliveries = store.list_deliveries(principal.user_id, limit=10)
        visible = [
            item
            for item in deliveries
            if item.channel is AlertChannel.IN_APP
            and item.status in {DeliveryStatus.SENT, DeliveryStatus.ACKNOWLEDGED}
        ]
        if not visible:
            st.caption("No in-app alerts yet.")
        for item in visible:
            st.markdown(f"**{item.subject}**")
            st.caption(item.created_at.strftime("%B %d, %Y at %H:%M UTC"))
            st.write(item.body)
            if item.status is DeliveryStatus.SENT:
                if st.button("Mark reviewed", key=f"ack-{item.delivery_id}"):
                    store.acknowledge(item.delivery_id, user_id=principal.user_id)
                    st.rerun()
            st.divider()

    with st.expander("Alert preferences"):
        timezone_name = st.text_input(
            "Timezone",
            value=preference.timezone_name,
            help="Use an IANA timezone such as America/Los_Angeles.",
        )
        delivery_hour = st.slider(
            "Preferred local delivery hour",
            min_value=0,
            max_value=23,
            value=preference.delivery_hour,
        )
        channel_values = [value.value for value in AlertChannel]
        selected_channels = st.multiselect(
            "Delivery channels",
            options=channel_values,
            default=[value.value for value in preference.channels],
        )
        canonical_topics = (
            AlertTopic.CIO_DECISION,
            AlertTopic.THESIS,
            AlertTopic.OPPORTUNITY,
            AlertTopic.IMPLEMENTATION,
            AlertTopic.EVIDENCE,
            AlertTopic.DAILY_BRIEFING,
        )
        topic_values = [value.value for value in canonical_topics]
        selected_topics = st.multiselect(
            "Notify me about",
            options=topic_values,
            default=[
                value.value for value in preference.topics if value in canonical_topics
            ],
        )
        email_address = st.text_input(
            "Email address",
            value=preference.email_address or principal.email,
            disabled=AlertChannel.EMAIL.value not in selected_channels,
        )
        if AlertChannel.EMAIL.value in selected_channels and not settings.smtp_host:
            st.warning(
                "Email delivery is not configured in this environment. "
                "In-app alerts remain available."
            )
        if st.button("Save alert preferences"):
            try:
                channels = tuple(AlertChannel(value) for value in selected_channels)
                topics = tuple(AlertTopic(value) for value in selected_topics)
                if AlertChannel.EMAIL in channels and not settings.smtp_host:
                    raise ValueError("email delivery is not configured")
                updated = DeliveryPreference(
                    user_id=principal.user_id,
                    timezone_name=timezone_name,
                    delivery_hour=delivery_hour,
                    channels=channels,
                    topics=topics,
                    email_address=(
                        email_address
                        if AlertChannel.EMAIL in channels
                        else principal.email
                    ),
                )
                store.save_preference(updated)
            except (TypeError, ValueError) as error:
                st.error(str(error))
            else:
                st.success("Alert preferences saved.")
                st.rerun()


def _authorized_bindings(principal) -> dict[str, object]:
    """Build session-local adapters for the sole canonical portfolio."""

    original_get_details = portfolio_services.get_mandate_details
    original_get_trades = portfolio_services.get_trade_history
    original_get_totals = portfolio_services.get_portfolio_totals

    def authorized_details(mandate_code: str = CANONICAL_PORTFOLIO_CODE):
        if mandate_code.strip().upper() != CANONICAL_PORTFOLIO_CODE:
            return None
        if not principal.can_access_mandate(CANONICAL_PORTFOLIO_CODE):
            return None
        return original_get_details(CANONICAL_PORTFOLIO_CODE)

    def authorized_trades(
        mandate_code: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if mandate_code is not None and mandate_code.strip().upper() != CANONICAL_PORTFOLIO_CODE:
            return []
        if not principal.can_access_mandate(CANONICAL_PORTFOLIO_CODE):
            return []
        return original_get_trades(CANONICAL_PORTFOLIO_CODE, limit=limit)

    def authorized_totals() -> dict:
        if not principal.can_access_mandate(CANONICAL_PORTFOLIO_CODE):
            return {
                "mandate_count": 0,
                "portfolio_count": 0,
                "starting_capital": 0.0,
                "starting": 0.0,
                "cash": 0.0,
                "nav": 0.0,
                "total_return": 0.0,
            }
        return original_get_totals()

    return {
        "get_mandate_details": authorized_details,
        "get_portfolio_totals": authorized_totals,
        "get_trade_history": authorized_trades,
    }


def _authorized_source() -> str:
    source = Path("app.py").read_text(encoding="utf-8")
    source = source.replace(
        '''st.set_page_config(
    page_title="Capital Intelligence Platform",
    page_icon="📊",
    layout="wide",
)


''',
        "",
        1,
    )
    source = source.replace(
        '''from core.portfolio import (
    get_mandate_details,
    get_portfolio_totals,
    get_trade_history,
)
''',
        "",
        1,
    )
    return source


principal = _principal()
if principal is None:
    _login_screen()

with st.sidebar:
    st.caption(f"Signed in as **{principal.display_name}**")
    _render_alert_controls(principal)
    if st.button("Sign out"):
        token = st.session_state.get("access_token")
        if token:
            authentication_service().store.logout(token)
        _clear_session()
        st.rerun()

execution_globals = {
    "__name__": "__main__",
    "authenticated_principal": principal,
    **_authorized_bindings(principal),
}
exec(compile(_authorized_source(), "app.py", "exec"), execution_globals)
