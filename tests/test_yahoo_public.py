from __future__ import annotations

import pytest

from providers.yahoo_public import YahooPublicProviderError, YahooPublicSession


class _Response:
    def __init__(self, *, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected Yahoo request")
        return self.responses.pop(0)


def test_option_request_establishes_cookie_and_crumb():
    session = _Session(
        [
            _Response(status_code=404),
            _Response(text="crumb-1"),
            _Response(payload={"optionChain": {"result": [{"expirationDates": [1]}]}}),
        ]
    )
    client = YahooPublicSession(session=session)

    payload = client.get_json(
        "https://query2.finance.yahoo.com/v7/finance/options/SPY",
        require_crumb=True,
    )

    assert payload["optionChain"]["result"][0]["expirationDates"] == [1]
    assert [item[0] for item in session.calls] == [
        YahooPublicSession.COOKIE_URL,
        YahooPublicSession.CRUMB_URL,
        "https://query2.finance.yahoo.com/v7/finance/options/SPY",
    ]
    assert session.calls[-1][1]["params"]["crumb"] == "crumb-1"


def test_authorization_failure_refreshes_crumb_once():
    session = _Session(
        [
            _Response(status_code=404),
            _Response(text="crumb-1"),
            _Response(status_code=401, payload={}),
            _Response(status_code=404),
            _Response(text="crumb-2"),
            _Response(payload={"ok": True}),
        ]
    )
    client = YahooPublicSession(session=session)

    assert client.get_json("https://example.test/options", require_crumb=True) == {
        "ok": True
    }
    option_calls = [item for item in session.calls if item[0] == "https://example.test/options"]
    assert option_calls[0][1]["params"]["crumb"] == "crumb-1"
    assert option_calls[1][1]["params"]["crumb"] == "crumb-2"


def test_invalid_crumb_fails_closed():
    client = YahooPublicSession(
        session=_Session(
            [
                _Response(status_code=404),
                _Response(text="<html>consent required</html>"),
            ]
        )
    )

    with pytest.raises(YahooPublicProviderError, match="invalid crumb"):
        client.get_json("https://example.test/options", require_crumb=True)


def test_non_object_json_fails_closed():
    client = YahooPublicSession(
        session=_Session([_Response(payload=[1, 2, 3])])
    )

    with pytest.raises(YahooPublicProviderError, match="non-object"):
        client.get_json("https://example.test/chart")
