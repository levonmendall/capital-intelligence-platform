from run_manual_cio_diagnostic import _diagnostic_audit_cycle_key


def test_release_diagnostic_audit_retains_production_context_cycle_key() -> None:
    context_cycle_key = "canonical-cio:America/Los_Angeles:2026-08-06"
    execution_cycle_key = (
        context_cycle_key
        + ":event:manual-diagnostic-render-release-d2068d4a153cf8fa141f9e7d8faace14b031a523"
    )

    assert (
        _diagnostic_audit_cycle_key(
            context_cycle_key=context_cycle_key,
            execution_cycle_key=execution_cycle_key,
        )
        == context_cycle_key
    )


def test_release_diagnostic_audit_rejects_missing_context_cycle_key() -> None:
    try:
        _diagnostic_audit_cycle_key(
            context_cycle_key="   ",
            execution_cycle_key="canonical-cio:event:manual-diagnostic",
        )
    except ValueError as error:
        assert "production context cycle key" in str(error)
    else:
        raise AssertionError("missing production context lineage must fail closed")
