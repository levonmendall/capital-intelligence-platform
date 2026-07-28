from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(f"{label} was not found exactly once")
    return source.replace(old, new, 1)


provider = Path("providers/alpaca_paper.py")
source = provider.read_text(encoding="utf-8")

old_helper = '''def _environment_value(*names: str, default: str = "") -> str:
    """Return the first non-empty credential/configuration alias without logging it."""

    for name in names:
        value = os.getenv(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


'''
new_helper = old_helper + '''def _environment_values(*names: str) -> tuple[tuple[str, str], ...]:
    """Return unique non-empty environment aliases while preserving priority."""

    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in names:
        value = os.getenv(name)
        normalized = value.strip() if isinstance(value, str) else ""
        if normalized and normalized not in seen:
            result.append((name, normalized))
            seen.add(normalized)
    return tuple(result)


'''
source = replace_once(source, old_helper, new_helper, "environment helper block")

old_timeout = '''        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")

    @classmethod
    def from_env(cls) -> "AlpacaPaperSettings":
'''
new_timeout = '''        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")

    def validate_provider_scope(self) -> None:
        host = (urlparse(self.paper_base_url).hostname or "").lower()
        if host != "paper-api.alpaca.markets":
            raise AlpacaPaperProviderError(
                "APCA_API_BASE_URL must use the Alpaca paper endpoint; live brokerage endpoints are prohibited"
            )
        if self.data_feed.lower() != "iex":
            raise AlpacaPaperProviderError(
                "the free paper pilot requires APCA_DATA_FEED=iex"
            )

    @classmethod
    def from_env(cls) -> "AlpacaPaperSettings":
'''
source = replace_once(source, old_timeout, new_timeout, "settings timeout block")

old_tail = '''        host = (urlparse(settings.paper_base_url).hostname or "").lower()
        if host != "paper-api.alpaca.markets":
            raise AlpacaPaperProviderError(
                "APCA_API_BASE_URL must use the Alpaca paper endpoint; live brokerage endpoints are prohibited"
            )
        if settings.data_feed.lower() != "iex":
            raise AlpacaPaperProviderError(
                "the free paper pilot requires APCA_DATA_FEED=iex"
            )
        return settings


class AlpacaPaperClient:
'''
new_tail = '''        settings.validate_provider_scope()
        return settings

    @classmethod
    def candidates_from_env(cls) -> tuple[tuple[str, "AlpacaPaperSettings"], ...]:
        keys = _environment_values(
            "APCA_API_KEY_ID",
            "ALPACA_API_KEY_ID",
            "ALPACA_API_KEY",
        )
        secrets = _environment_values(
            "APCA_API_SECRET_KEY",
            "ALPACA_API_SECRET_KEY",
            "ALPACA_SECRET_KEY",
            "ALPACA_API_SECRET",
        )
        if not keys:
            raise ValueError("no Alpaca paper API key ID is configured")
        if not secrets:
            raise ValueError("no Alpaca paper API secret is configured")
        paper_base_url = _environment_value(
            "APCA_API_BASE_URL",
            "ALPACA_API_BASE_URL",
            default=DEFAULT_PAPER_BASE_URL,
        )
        data_base_url = _environment_value(
            "APCA_DATA_BASE_URL",
            "ALPACA_DATA_BASE_URL",
            default=DEFAULT_DATA_BASE_URL,
        )
        data_feed = _environment_value(
            "APCA_DATA_FEED",
            "ALPACA_DATA_FEED",
            default=DEFAULT_DATA_FEED,
        )
        result: list[tuple[str, AlpacaPaperSettings]] = []
        for key_name, key_value in keys:
            for secret_name, secret_value in secrets:
                settings = cls(
                    api_key_id=key_value,
                    secret_key=secret_value,
                    paper_base_url=paper_base_url,
                    data_base_url=data_base_url,
                    data_feed=data_feed,
                )
                settings.validate_provider_scope()
                result.append((f"{key_name}+{secret_name}", settings))
        return tuple(result)


class AlpacaPaperClient:
'''
source = replace_once(source, old_tail, new_tail, "settings validation tail")

old_factory = '''def create_alpaca_paper_client() -> AlpacaPaperClient:
    return AlpacaPaperClient(AlpacaPaperSettings.from_env())
'''
new_factory = '''def create_alpaca_paper_client(
    *,
    http_get: Callable[..., Any] | None = None,
) -> AlpacaPaperClient:
    candidates = AlpacaPaperSettings.candidates_from_env()
    for _label, settings in candidates:
        client = AlpacaPaperClient(settings, http_get=http_get)
        try:
            client.account()
        except AlpacaPaperProviderError:
            continue
        return client
    raise AlpacaPaperProviderError(
        f"no configured Alpaca paper credential pair authenticated ({len(candidates)} combinations attempted)"
    )
'''
source = replace_once(source, old_factory, new_factory, "client factory block")
provider.write_text(source, encoding="utf-8")

operations = Path("operations/free_paper_pilot.py")
ops = operations.read_text(encoding="utf-8")
ops = replace_once(
    ops,
    '''    AlpacaPaperSettings,
)
''',
    '''    AlpacaPaperSettings,
    create_alpaca_paper_client,
)
''',
    "operations provider import block",
)
ops = replace_once(
    ops,
    '''def default_alpaca_client() -> AlpacaPaperClient:
    return AlpacaPaperClient(AlpacaPaperSettings.from_env())
''',
    '''def default_alpaca_client() -> AlpacaPaperClient:
    return create_alpaca_paper_client()
''',
    "default Alpaca client block",
)
operations.write_text(ops, encoding="utf-8")

workflow = Path(".github/workflows/free-paper-pilot-readiness.yml")
wf = workflow.read_text(encoding="utf-8")
wf = wf.replace('      - pr-166-free-paper-pilot\n', '')
wf = replace_once(
    wf,
    '''      APCA_API_KEY_ID: ${{ secrets.APCA_API_KEY_ID || secrets.ALPACA_API_KEY_ID || secrets.ALPACA_API_KEY }}
      APCA_API_SECRET_KEY: ${{ secrets.APCA_API_SECRET_KEY || secrets.ALPACA_API_SECRET_KEY || secrets.ALPACA_SECRET_KEY || secrets.ALPACA_API_SECRET }}
''',
    '''      APCA_API_KEY_ID: ${{ secrets.APCA_API_KEY_ID }}
      ALPACA_API_KEY_ID: ${{ secrets.ALPACA_API_KEY_ID }}
      ALPACA_API_KEY: ${{ secrets.ALPACA_API_KEY }}
      APCA_API_SECRET_KEY: ${{ secrets.APCA_API_SECRET_KEY }}
      ALPACA_API_SECRET_KEY: ${{ secrets.ALPACA_API_SECRET_KEY }}
      ALPACA_SECRET_KEY: ${{ secrets.ALPACA_SECRET_KEY }}
      ALPACA_API_SECRET: ${{ secrets.ALPACA_API_SECRET }}
''',
    "workflow credential environment block",
)
wf = replace_once(
    wf,
    '''      - name: Require both Alpaca paper credentials
        shell: bash
        run: |
          if [ -z "${APCA_API_KEY_ID}" ]; then
            echo "Missing Alpaca paper key secret. Supported names: APCA_API_KEY_ID, ALPACA_API_KEY_ID, or ALPACA_API_KEY."
            exit 2
          fi
          if [ -z "${APCA_API_SECRET_KEY}" ]; then
            echo "Missing Alpaca paper secret. Supported names: APCA_API_SECRET_KEY, ALPACA_API_SECRET_KEY, ALPACA_SECRET_KEY, or ALPACA_API_SECRET."
            exit 2
          fi
''',
    '''      - name: Require Alpaca paper credential candidates
        shell: bash
        run: |
          if [ -z "${APCA_API_KEY_ID}${ALPACA_API_KEY_ID}${ALPACA_API_KEY}" ]; then
            echo "Missing Alpaca paper key ID candidate."
            exit 2
          fi
          if [ -z "${APCA_API_SECRET_KEY}${ALPACA_API_SECRET_KEY}${ALPACA_SECRET_KEY}${ALPACA_API_SECRET}" ]; then
            echo "Missing Alpaca paper secret candidate."
            exit 2
          fi
''',
    "workflow credential check block",
)
workflow.write_text(wf, encoding="utf-8")

tests = Path("tests/test_free_paper_pilot.py")
test_source = tests.read_text(encoding="utf-8")
test_source = replace_once(
    test_source,
    '''    AlpacaPaperSettings,
)
''',
    '''    AlpacaPaperSettings,
    create_alpaca_paper_client,
)
''',
    "test provider import block",
)
addition = '''

def test_authenticated_pair_selection_uses_matching_credentials(monkeypatch) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "wrong-key")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "matching-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "wrong-secret")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "matching-secret")

    attempts: list[tuple[str, str]] = []

    def authenticated_get(url: str, **kwargs: Any) -> _Response:
        headers = kwargs["headers"]
        pair = (headers["APCA-API-KEY-ID"], headers["APCA-API-SECRET-KEY"])
        attempts.append(pair)
        if pair == ("matching-key", "matching-secret") and url.endswith("/v2/account"):
            return _Response({"status": "ACTIVE"})
        return _Response({"message": "unauthorized"}, status_code=401)

    client = create_alpaca_paper_client(http_get=authenticated_get)

    assert client.settings.api_key_id == "matching-key"
    assert client.settings.secret_key == "matching-secret"
    assert attempts[-1] == ("matching-key", "matching-secret")
    assert len(attempts) == 4
'''
if "test_authenticated_pair_selection_uses_matching_credentials" not in test_source:
    test_source = test_source.rstrip() + addition + "\n"
tests.write_text(test_source, encoding="utf-8")

for temporary in (
    Path(".github/workflows/repair-alpaca-authenticated-pairing.yml"),
    Path(".github/workflows/apply-alpaca-authenticated-pairing.yml"),
    Path("tools/repair_alpaca_pairing.py"),
):
    if temporary.exists():
        temporary.unlink()
