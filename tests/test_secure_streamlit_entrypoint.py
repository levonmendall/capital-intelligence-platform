"""Regression checks for authenticated execution of the deployment-safe UI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE_CONFIG_BLOCK = '''st.set_page_config(
    page_title="Capital Intelligence Platform",
    page_icon="📊",
    layout="wide",
)


'''
PORTFOLIO_IMPORT_BLOCK = '''from core.portfolio import (
    get_mandate_details,
    get_portfolio_totals,
    get_trade_history,
)
'''


def test_entrypoint_builds_page_configuration_block_dynamically() -> None:
    entrypoint = (ROOT / "app.py").read_text(encoding="utf-8")

    assert PAGE_CONFIG_BLOCK not in entrypoint
    assert '_page_config_block = "".join' in entrypoint
    assert '_source.replace(_page_config_block, "", 1)' in entrypoint


def test_secure_source_preprocessing_leaves_runtime_strip_logic_intact() -> None:
    entrypoint = (ROOT / "app.py").read_text(encoding="utf-8")

    transformed = entrypoint.replace(PAGE_CONFIG_BLOCK, "", 1)
    transformed = transformed.replace(PORTFOLIO_IMPORT_BLOCK, "", 1)

    compile(transformed, "app.py", "exec")
    assert '_page_config_block = "".join' in transformed
    assert PORTFOLIO_IMPORT_BLOCK in transformed


def test_authorized_entrypoint_can_remove_duplicate_configuration_from_implementation() -> None:
    implementation = (ROOT / "app_impl.py").read_text(encoding="utf-8")

    assert implementation.count(PAGE_CONFIG_BLOCK) == 1
    assert implementation.count(PORTFOLIO_IMPORT_BLOCK) == 1
    authorized_source = implementation.replace(PAGE_CONFIG_BLOCK, "", 1)
    authorized_source = authorized_source.replace(PORTFOLIO_IMPORT_BLOCK, "", 1)

    compile(authorized_source, "app_impl.py", "exec")
    assert PAGE_CONFIG_BLOCK not in authorized_source
    assert PORTFOLIO_IMPORT_BLOCK not in authorized_source
