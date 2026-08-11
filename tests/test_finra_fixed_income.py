from __future__ import annotations

import pytest

from providers.finra_fixed_income import (
    FINRA_TOKEN_ENDPOINT,
    FinraFixedIncomeError,
    FinraFixedIncomeProvider,
    build_finra_fixed_income_provider,
)


class _Response:
    def __init__(self, payload, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_finra_oauth_and_fixed_income_probe_is_credential_safe() -> None:
    calls = []

    def http_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return _Response(
            {
                "access_token": "temporary-bearer-token",
                "token_type": "Bearer",
                "expires_in": "3600",
            }
        )

    def http_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        assert kwargs["headers"]["Authorization"] == "Bearer temporary-bearer-token"
        return _Response(
            [
                {
                    "tradeDate": "2026-08-10",
                    "productCategory": "Nominal Coupons",
                    "dealerCustomerVolume": 10.5,
                }
            ]
        )

    provider = FinraFixedIncomeProvider(
        "client-id",
        "client-secret",
        http_post=http_post,
        http_get=http_get,
    )
    evidence = provider.probe_treasury_daily_aggregates().to_dict()

    assert calls[0][1] == FINRA_TOKEN_ENDPOINT
    assert calls[0][2]["params"] == {"grant_type": "client_credentials"}
    assert calls[0][2]["auth"] == ("client-id", "client-secret")
    assert evidence["dataset"] == "treasuryDailyAggregates"
    assert evidence["record_available"] is True
    assert evidence["credential_values_included"] is False
    assert "temporary-bearer-token" not in str(evidence)
    assert "client-secret" not in str(evidence)


def test_finra_build_accepts_capital_intelligence_aliases() -> None:
    provider = build_finra_fixed_income_provider(
        {
            "CAPITAL_INTELLIGENCE_FINRA_CLIENT_ID": "alias-id",
            "CAPITAL_INTELLIGENCE_FINRA_CLIENT_SECRET": "alias-secret",
        }
    )

    assert provider is not None


def test_finra_build_returns_none_when_not_configured() -> None:
    assert build_finra_fixed_income_provider({}) is None


def test_finra_build_fails_closed_on_partial_credentials() -> None:
    with pytest.raises(FinraFixedIncomeError, match="both client ID and client secret"):
        build_finra_fixed_income_provider({"FINRA_CLIENT_ID": "id-only"})


def test_finra_probe_fails_closed_on_oauth_rejection() -> None:
    provider = FinraFixedIncomeProvider(
        "client-id",
        "client-secret",
        http_post=lambda *_args, **_kwargs: _Response({}, status_code=401),
    )

    with pytest.raises(FinraFixedIncomeError, match="OAuth returned HTTP 401"):
        provider.probe_treasury_daily_aggregates()


def test_finra_probe_fails_closed_when_fixed_income_access_is_rejected() -> None:
    provider = FinraFixedIncomeProvider(
        "client-id",
        "client-secret",
        http_post=lambda *_args, **_kwargs: _Response(
            {"access_token": "token", "token_type": "Bearer", "expires_in": 3600}
        ),
        http_get=lambda *_args, **_kwargs: _Response({}, status_code=403),
    )

    with pytest.raises(FinraFixedIncomeError, match="Fixed Income returned HTTP 403"):
        provider.probe_treasury_daily_aggregates()
