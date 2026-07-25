"""Append-only SQLite history for investor goals and policy profiles."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from personal_cio.models import (
    GoalPriority,
    GoalType,
    InvestmentPolicyProfile,
    InvestorGoal,
    RiskCapacity,
    RiskPreference,
    goal_to_dict,
    policy_to_dict,
)


class SQLiteInvestmentPolicyStore:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if self.path.exists() and self.path.is_dir():
            raise ValueError("investment policy path must be a file")
        if not read_only:
            self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS investment_policy_profiles (
                    identifier TEXT PRIMARY KEY,
                    investor_identifier TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS investment_policy_investor_effective
                ON investment_policy_profiles (investor_identifier, effective_at DESC);

                CREATE TABLE IF NOT EXISTS investor_goals (
                    identifier TEXT PRIMARY KEY,
                    goal_key TEXT NOT NULL,
                    investor_identifier TEXT NOT NULL,
                    effective_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS investor_goals_investor_effective
                ON investor_goals (investor_identifier, goal_key, effective_at DESC);

                CREATE TRIGGER IF NOT EXISTS investment_policy_prevent_update
                BEFORE UPDATE ON investment_policy_profiles
                BEGIN
                    SELECT RAISE(ABORT, 'investment policy history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS investment_policy_prevent_delete
                BEFORE DELETE ON investment_policy_profiles
                BEGIN
                    SELECT RAISE(ABORT, 'investment policy history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS investor_goals_prevent_update
                BEFORE UPDATE ON investor_goals
                BEGIN
                    SELECT RAISE(ABORT, 'investor goal history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS investor_goals_prevent_delete
                BEFORE DELETE ON investor_goals
                BEGIN
                    SELECT RAISE(ABORT, 'investor goal history is append-only');
                END;
                """
            )

    def append_profile(
        self,
        profile: InvestmentPolicyProfile,
    ) -> InvestmentPolicyProfile:
        if self.read_only:
            raise PermissionError("investment policy store is read-only")
        if not isinstance(profile, InvestmentPolicyProfile):
            raise TypeError("profile must be an InvestmentPolicyProfile")
        payload = json.dumps(
            policy_to_dict(profile),
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM investment_policy_profiles WHERE identifier = ?",
                (profile.identifier,),
            ).fetchone()
            if row is not None:
                if row["payload_json"] != payload:
                    raise ValueError(
                        "policy identifier already exists with different content"
                    )
                return profile
            connection.execute(
                """
                INSERT INTO investment_policy_profiles
                (identifier, investor_identifier, effective_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    profile.identifier,
                    profile.investor_identifier,
                    profile.effective_at.isoformat(),
                    payload,
                ),
            )
        return profile

    def append_goal(self, goal: InvestorGoal) -> InvestorGoal:
        if self.read_only:
            raise PermissionError("investment policy store is read-only")
        if not isinstance(goal, InvestorGoal):
            raise TypeError("goal must be an InvestorGoal")
        payload = json.dumps(
            goal_to_dict(goal),
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM investor_goals WHERE identifier = ?",
                (goal.identifier,),
            ).fetchone()
            if row is not None:
                if row["payload_json"] != payload:
                    raise ValueError(
                        "goal identifier already exists with different content"
                    )
                return goal
            connection.execute(
                """
                INSERT INTO investor_goals
                (identifier, goal_key, investor_identifier, effective_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    goal.identifier,
                    goal.goal_key,
                    goal.investor_identifier,
                    goal.effective_at.isoformat(),
                    payload,
                ),
            )
        return goal

    def latest_profile(
        self,
        investor_identifier: str,
    ) -> InvestmentPolicyProfile | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM investment_policy_profiles
                WHERE investor_identifier = ?
                ORDER BY effective_at DESC, identifier DESC
                LIMIT 1
                """,
                (investor_identifier,),
            ).fetchone()
        return None if row is None else self._profile(json.loads(row["payload_json"]))

    def profile_history(
        self,
        investor_identifier: str,
        *,
        limit: int = 50,
    ) -> tuple[InvestmentPolicyProfile, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM investment_policy_profiles
                WHERE investor_identifier = ?
                ORDER BY effective_at DESC, identifier DESC
                LIMIT ?
                """,
                (investor_identifier, limit),
            ).fetchall()
        return tuple(
            self._profile(json.loads(row["payload_json"]))
            for row in rows
        )

    def goals(
        self,
        investor_identifier: str,
        *,
        history: bool = False,
    ) -> tuple[InvestorGoal, ...]:
        with self._connect() as connection:
            if history:
                rows = connection.execute(
                    """
                    SELECT payload_json FROM investor_goals
                    WHERE investor_identifier = ?
                    ORDER BY effective_at DESC, identifier DESC
                    """,
                    (investor_identifier,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT g.payload_json FROM investor_goals g
                    WHERE g.investor_identifier = ?
                    AND g.effective_at = (
                        SELECT MAX(g2.effective_at) FROM investor_goals g2
                        WHERE g2.investor_identifier = g.investor_identifier
                        AND g2.goal_key = g.goal_key
                    )
                    ORDER BY g.effective_at DESC, g.identifier DESC
                    """,
                    (investor_identifier,),
                ).fetchall()
        return tuple(
            self._goal(json.loads(row["payload_json"]))
            for row in rows
        )

    def readiness(self) -> tuple[bool, str]:
        try:
            with self._connect() as connection:
                connection.execute(
                    "SELECT COUNT(*) FROM investment_policy_profiles"
                ).fetchone()
                connection.execute(
                    "SELECT COUNT(*) FROM investor_goals"
                ).fetchone()
        except (OSError, sqlite3.Error) as error:
            return False, f"investment policy store is unavailable: {error}"
        return True, "investor goals and policy history are available"

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            if not self.path.exists():
                raise FileNotFoundError(self.path)
            encoded = quote(str(self.path.resolve()), safe="/")
            connection = sqlite3.connect(
                f"file:{encoded}?mode=ro",
                uri=True,
            )
            connection.execute("PRAGMA query_only = ON")
        else:
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _profile(payload: dict) -> InvestmentPolicyProfile:
        return InvestmentPolicyProfile(
            identifier=payload["identifier"],
            investor_identifier=payload["investor_identifier"],
            version=payload["version"],
            effective_at=datetime.fromisoformat(payload["effective_at"]),
            primary_objective=payload["primary_objective"],
            time_horizon_years=int(payload["time_horizon_years"]),
            risk_capacity=RiskCapacity(payload["risk_capacity"]),
            risk_preference=RiskPreference(payload["risk_preference"]),
            required_return=payload.get("required_return"),
            maximum_tolerable_drawdown=payload.get(
                "maximum_tolerable_drawdown"
            ),
            minimum_liquidity_months=int(
                payload.get("minimum_liquidity_months", 0)
            ),
            income_requirement=payload.get("income_requirement"),
            tax_sensitivity=payload.get("tax_sensitivity", "medium"),
            rebalance_tolerance=payload.get(
                "rebalance_tolerance",
                "moderate",
            ),
            supersedes_identifier=payload.get("supersedes_identifier"),
        )

    @staticmethod
    def _goal(payload: dict) -> InvestorGoal:
        return InvestorGoal(
            identifier=payload["identifier"],
            goal_key=payload["goal_key"],
            investor_identifier=payload["investor_identifier"],
            version=payload["version"],
            name=payload["name"],
            goal_type=GoalType(payload["goal_type"]),
            priority=GoalPriority(payload["priority"]),
            effective_at=datetime.fromisoformat(payload["effective_at"]),
            target_date=(
                None
                if payload.get("target_date") is None
                else date.fromisoformat(payload["target_date"])
            ),
            target_amount=payload.get("target_amount"),
            funded_amount=payload.get("funded_amount"),
            portfolio_codes=tuple(payload.get("portfolio_codes", ())),
            liquidity_required=bool(
                payload.get("liquidity_required", False)
            ),
            supersedes_identifier=payload.get("supersedes_identifier"),
        )
