"""Authenticated Streamlit entrypoint with per-session authorization adapters."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import streamlit as st

from api.config import ApiSettings
from api.repositories import DailySnapshotRepository
from core import portfolio as portfolio_services
from delivery import (
    AlertChannel,
    AlertTopic,
    DeliveryPreference,
    DeliveryStatus,
    SQLiteAlertStore,
)
from personal_cio import (
    GoalPriority,
    GoalType,
    InvestmentPolicyProfile,
    InvestorGoal,
    RiskCapacity,
    RiskPreference,
    SQLiteInvestmentPolicyStore as BaseInvestmentPolicyStore,
    build_personal_cio_brief,
)
from personalization import SQLiteInvestorMemoryStore as BaseInvestorMemoryStore
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
    path = settings.alert_database or settings.snapshot_database.with_name("alerts.db")
    return SQLiteAlertStore(path)


@st.cache_resource
def investment_policy_store() -> BaseInvestmentPolicyStore:
    settings = runtime_settings()
    return BaseInvestmentPolicyStore(
        settings.investor_memory_database.with_name("investment_policy.db")
    )


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
        topic_values = [value.value for value in AlertTopic]
        selected_topics = st.multiselect(
            "Notify me about",
            options=topic_values,
            default=[value.value for value in preference.topics],
        )
        email_address = st.text_input(
            "Email address",
            value=preference.email_address or principal.email,
            disabled=AlertChannel.EMAIL.value not in selected_channels,
        )
        minimum_conviction_change = st.slider(
            "Minimum conviction change",
            min_value=1,
            max_value=25,
            value=min(preference.minimum_conviction_change, 25),
            help="Conviction changes smaller than this remain silent.",
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
                    minimum_conviction_change=minimum_conviction_change,
                )
                store.save_preference(updated)
            except (TypeError, ValueError) as error:
                st.error(str(error))
            else:
                st.success("Alert preferences saved.")
                st.rerun()


def _render_objective_controls(principal) -> None:
    investor_identifier = principal.investor_identifier or principal.user_id
    store = investment_policy_store()
    profile = store.latest_profile(investor_identifier)
    goals = store.goals(investor_identifier)
    can_write = principal.can_access_investor(
        investor_identifier,
        write=True,
    )

    with st.expander("Investment objectives"):
        if profile is None:
            st.warning(
                "Personal guidance is incomplete until objectives are recorded."
            )
        else:
            st.caption(
                f"Objective: {profile.primary_objective} · "
                f"Risk capacity: {profile.risk_capacity.value} · "
                f"Risk preference: {profile.risk_preference.value}"
            )
        st.caption(f"{len(goals)} active goal(s) recorded.")
        if not can_write:
            st.info("Your access is read-only for this investor profile.")
            return

        with st.form("investment-policy-form"):
            objective = st.text_input(
                "Primary objective",
                value=(
                    profile.primary_objective
                    if profile
                    else "long_term_growth"
                ),
            )
            horizon = st.slider(
                "Time horizon in years",
                1,
                50,
                value=(profile.time_horizon_years if profile else 10),
            )
            capacity_values = [value.value for value in RiskCapacity]
            capacity = st.selectbox(
                "Financial risk capacity",
                capacity_values,
                index=(
                    capacity_values.index(profile.risk_capacity.value)
                    if profile
                    else 1
                ),
            )
            preference_values = [value.value for value in RiskPreference]
            preference = st.selectbox(
                "Risk preference",
                preference_values,
                index=(
                    preference_values.index(profile.risk_preference.value)
                    if profile
                    else 1
                ),
            )
            required_return = st.number_input(
                "Required annual return (%)",
                min_value=0.0,
                max_value=100.0,
                value=(
                    100 * profile.required_return
                    if profile and profile.required_return is not None
                    else 0.0
                ),
                step=0.5,
            )
            drawdown = st.number_input(
                "Maximum tolerable drawdown (%)",
                min_value=0.0,
                max_value=100.0,
                value=(
                    100 * profile.maximum_tolerable_drawdown
                    if profile
                    and profile.maximum_tolerable_drawdown is not None
                    else 20.0
                ),
                step=1.0,
            )
            liquidity_months = st.slider(
                "Minimum liquidity reserve (months)",
                0,
                60,
                value=(profile.minimum_liquidity_months if profile else 6),
            )
            save_policy = st.form_submit_button("Save new policy version")
        if save_policy:
            try:
                updated = InvestmentPolicyProfile(
                    identifier=(
                        f"investment-policy:{investor_identifier}:{uuid4()}"
                    ),
                    investor_identifier=investor_identifier,
                    version="investment-policy-profile.v1",
                    effective_at=datetime.now(timezone.utc),
                    primary_objective=objective,
                    time_horizon_years=horizon,
                    risk_capacity=RiskCapacity(capacity),
                    risk_preference=RiskPreference(preference),
                    required_return=(
                        required_return / 100 if required_return else None
                    ),
                    maximum_tolerable_drawdown=(
                        drawdown / 100 if drawdown else None
                    ),
                    minimum_liquidity_months=liquidity_months,
                    supersedes_identifier=(
                        None if profile is None else profile.identifier
                    ),
                )
                store.append_profile(updated)
            except (TypeError, ValueError) as error:
                st.error(str(error))
            else:
                st.success("Investment policy version recorded.")
                st.rerun()

        with st.form("investor-goal-form"):
            goal_key = st.text_input(
                "Goal key",
                placeholder="retirement",
            )
            goal_name = st.text_input(
                "Goal name",
                placeholder="Retirement",
            )
            goal_type = st.selectbox(
                "Goal type",
                [value.value for value in GoalType],
            )
            priority = st.selectbox(
                "Priority",
                [value.value for value in GoalPriority],
            )
            has_target_date = st.checkbox("This goal has a target date")
            target_date = (
                st.date_input("Target date", value=date.today())
                if has_target_date
                else None
            )
            target_amount = st.number_input(
                "Target amount ($)",
                min_value=0.0,
                value=0.0,
                step=1000.0,
            )
            funded_amount = st.number_input(
                "Already funded ($)",
                min_value=0.0,
                value=0.0,
                step=1000.0,
            )
            mandate_codes = [
                str(item["code"])
                for item in portfolio_services.get_mandates()
                if principal.can_access_mandate(str(item["code"]))
            ]
            portfolio_codes = st.multiselect(
                "Portfolios funding this goal",
                mandate_codes,
            )
            liquidity_required = st.checkbox(
                "This goal requires accessible cash"
            )
            save_goal = st.form_submit_button("Save new goal version")
        if save_goal:
            previous = next(
                (
                    item
                    for item in goals
                    if item.goal_key == goal_key.strip()
                ),
                None,
            )
            try:
                updated_goal = InvestorGoal(
                    identifier=(
                        f"investor-goal:{investor_identifier}:"
                        f"{goal_key}:{uuid4()}"
                    ),
                    goal_key=goal_key,
                    investor_identifier=investor_identifier,
                    version="investor-goal.v1",
                    name=goal_name,
                    goal_type=GoalType(goal_type),
                    priority=GoalPriority(priority),
                    effective_at=datetime.now(timezone.utc),
                    target_date=target_date,
                    target_amount=(target_amount or None),
                    funded_amount=(funded_amount or None),
                    portfolio_codes=tuple(portfolio_codes),
                    liquidity_required=liquidity_required,
                    supersedes_identifier=(
                        None if previous is None else previous.identifier
                    ),
                )
                store.append_goal(updated_goal)
            except (TypeError, ValueError) as error:
                st.error(str(error))
            else:
                st.success("Investor goal version recorded.")
                st.rerun()


def _authorized_portfolios(principal) -> tuple[dict, ...]:
    portfolios: list[dict] = []
    for item in portfolio_services.get_mandates():
        code = str(item["code"])
        if not principal.can_access_mandate(code):
            continue
        portfolios.append(
            portfolio_services.get_mandate_details(code) or item
        )
    return tuple(portfolios)


def _personal_cio_brief(principal):
    settings = runtime_settings()
    payload = DailySnapshotRepository(
        settings.snapshot_database
    ).latest_payload()
    if payload is None:
        return None
    investor_identifier = principal.investor_identifier or principal.user_id
    store = investment_policy_store()
    return build_personal_cio_brief(
        investor_identifier,
        daily_snapshot=payload,
        profile=store.latest_profile(investor_identifier),
        goals=store.goals(investor_identifier),
        portfolios=_authorized_portfolios(principal),
    )


def _authorized_bindings(principal) -> dict[str, object]:
    """Build session-local portfolio and memory adapters for app.py."""

    original_get_mandates = portfolio_services.get_mandates
    original_get_details = portfolio_services.get_mandate_details
    original_get_trades = portfolio_services.get_trade_history

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
            items.extend(
                original_get_trades(str(mandate["code"]), limit=limit)
            )
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

    class AuthorizedMemoryStore(BaseInvestorMemoryStore):
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
            if not principal.can_access_investor(
                investor_identifier,
                write=True,
            ):
                raise PermissionError(
                    "investor reflection access is not authorized"
                )
            return super().append(
                replace(event, investor_identifier=investor_identifier)
            )

    return {
        "get_mandate_details": authorized_details,
        "get_mandates": authorized_mandates,
        "get_portfolio_totals": authorized_totals,
        "get_trade_history": authorized_trades,
        "SQLiteInvestorMemoryStore": AuthorizedMemoryStore,
        "personal_cio_brief": _personal_cio_brief(principal),
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
    get_mandates,
    get_portfolio_totals,
    get_trade_history,
)
''',
        "",
        1,
    )
    source = source.replace(
        "    SQLiteInvestorMemoryStore,\n",
        "",
        1,
    )
    source = source.replace(
        "@st.cache_resource\ndef investor_memory_store",
        "def investor_memory_store",
        1,
    )
    source = source.replace(
        '''if page == "Today":
    st.subheader("Today's Capital Intelligence")
''',
        '''if page == "Today":
    st.subheader("Today's Capital Intelligence")

    if personal_cio_brief is not None:
        alignment = personal_cio_brief.portfolio_alignment
        alignment_text = "—" if alignment.score is None else str(alignment.score)
        alignment_delta = None if alignment.score is None else alignment.status.title()
        st.metric("Portfolio Alignment", alignment_text, delta=alignment_delta)
        st.caption(alignment.explanation)
        st.markdown("### What changed?")
        st.write(personal_cio_brief.what_changed)
        st.markdown("### Why does it matter?")
        st.write(personal_cio_brief.why_it_matters)
        st.markdown("### How does it affect my portfolio?")
        st.write(personal_cio_brief.portfolio_effect)
        st.markdown("### Should I do anything?")
        action_label = personal_cio_brief.action_status.value.replace("_", " ").title()
        if personal_cio_brief.action_status.value == "no_action":
            st.success(f"{action_label}: {personal_cio_brief.recommended_action}")
        elif personal_cio_brief.action_status.value in {"review", "consider_change", "urgent_review"}:
            st.warning(f"{action_label}: {personal_cio_brief.recommended_action}")
        else:
            st.info(f"{action_label}: {personal_cio_brief.recommended_action}")
        with st.expander("Evidence and review conditions"):
            for condition in personal_cio_brief.review_conditions:
                st.write(f"• {condition}")
            if personal_cio_brief.evidence_identifiers:
                st.caption("Evidence lineage: " + ", ".join(personal_cio_brief.evidence_identifiers))
        st.divider()
''',
        1,
    )
    return source


principal = _principal()
if principal is None:
    _login_screen()

with st.sidebar:
    st.caption(f"Signed in as **{principal.display_name}**")
    _render_objective_controls(principal)
    _render_alert_controls(principal)
    if st.button("Sign out"):
        token = st.session_state.get("access_token")
        if token:
            authentication_service().store.logout(token)
        _clear_session()
        st.rerun()

execution_globals = {
    "__name__": "__main__",
    **_authorized_bindings(principal),
}
exec(compile(_authorized_source(), "app.py", "exec"), execution_globals)
