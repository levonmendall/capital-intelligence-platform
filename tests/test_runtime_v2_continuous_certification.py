from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import operations.capability_scoped_render_bootstrap as capability_bootstrap
import run_bounded_continuous_evidence_plane as bounded_evidence
import run_render_service_memory_safe as memory_safe
from operations.capability_scoped_release_diagnostic import _capability_release_environment


class RuntimeV2ProcessGraphTests(unittest.TestCase):
    def test_only_serving_children_are_critical_in_memory_safe_graph(self) -> None:
        specs = {
            spec.name: spec
            for spec in memory_safe.memory_safe_managed_processes(
                port=10000,
                python_executable="python",
            )
        }

        self.assertTrue(specs["api"].critical)
        self.assertTrue(specs["streamlit"].critical)
        self.assertFalse(specs["cio-paper-operator"].critical)
        self.assertFalse(specs["global-public-evidence"].critical)
        self.assertFalse(specs["historical-backfill"].critical)
        self.assertFalse(specs["encrypted-backup"].critical)

        self.assertEqual(
            specs["cio-paper-operator"].command[1:4],
            ("run_bounded_render_worker.py", "cio-paper-operator", "--loop"),
        )
        self.assertEqual(
            specs["global-public-evidence"].command[1:4],
            ("run_bounded_render_worker.py", "global-public-evidence", "--loop"),
        )

    def test_bond_transition_does_not_relax_comprehensive_discovery(self) -> None:
        values = {
            "CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE": "true",
            "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
            "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED": "false",
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE": "false",
        }
        observed: dict[str, object] = {}
        storage_report = SimpleNamespace(to_dict=lambda: {})

        def run_supervisor(*, environment, **kwargs):
            observed["environment"] = dict(environment)
            observed["kwargs"] = dict(kwargs)
            return 0

        with (
            patch.object(
                memory_safe.render_supervisor,
                "prepare_render_environment",
                side_effect=lambda environment: environment,
            ),
            patch.object(
                memory_safe.render_bootstrap,
                "reclaim_from_environment",
                return_value=storage_report,
            ),
            patch.object(memory_safe.render_bootstrap, "_log"),
            patch.object(
                memory_safe,
                "_start_release_diagnostic_after_prequalification",
                return_value=None,
            ),
            patch.object(
                memory_safe.render_supervisor,
                "run_supervisor",
                side_effect=run_supervisor,
            ),
        ):
            self.assertEqual(memory_safe.run_memory_safe_render_service(values), 0)

        environment = observed["environment"]
        self.assertIsInstance(environment, dict)
        self.assertEqual(
            environment["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY"],
            "true",
        )
        self.assertEqual(observed["kwargs"], {})

    def test_render_evidence_plane_serializes_nested_certification_workers(self) -> None:
        observed: dict[str, object] = {}

        def run_isolated(_spec, *, values, lane_wait_seconds):
            observed["values"] = dict(values)
            observed["lane_wait_seconds"] = lane_wait_seconds
            return 0

        with patch.object(bounded_evidence, "_run_isolated_once", side_effect=run_isolated):
            self.assertEqual(
                bounded_evidence.run_continuous_once(
                    {
                        "RENDER": "true",
                        "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "6",
                    }
                ),
                0,
            )

        values = observed["values"]
        self.assertIsInstance(values, dict)
        self.assertEqual(values["CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS"], "1")
        self.assertEqual(observed["lane_wait_seconds"], 300.0)

    def test_non_render_evidence_plane_preserves_configured_certification_workers(self) -> None:
        observed: dict[str, object] = {}

        def run_isolated(_spec, *, values, lane_wait_seconds):
            observed["values"] = dict(values)
            return 0

        with patch.object(bounded_evidence, "_run_isolated_once", side_effect=run_isolated):
            self.assertEqual(
                bounded_evidence.run_continuous_once(
                    {"CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "4"}
                ),
                0,
            )

        values = observed["values"]
        self.assertIsInstance(values, dict)
        self.assertEqual(values["CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS"], "4")


class RuntimeV2CertificationScopeTests(unittest.TestCase):
    def test_capability_release_environment_preserves_all_market_requirements(self) -> None:
        def original(_values):
            return {
                "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "false",
                "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_MARKET_DISCOVERY": "false",
                "CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE": "false",
            }

        diagnostic = _capability_release_environment(original, {"RENDER": "true"})

        self.assertEqual(
            diagnostic["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY"],
            "true",
        )
        self.assertEqual(
            diagnostic["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_MARKET_DISCOVERY"],
            "true",
        )
        self.assertEqual(
            diagnostic["CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE"],
            "true",
        )
        self.assertEqual(
            diagnostic["CAPITAL_INTELLIGENCE_RUN_COMPREHENSIVE_DISCOVERY"],
            "true",
        )
        self.assertEqual(
            diagnostic["CAPITAL_INTELLIGENCE_DIAGNOSTIC_ALLOW_COMPREHENSIVE_DISCOVERY"],
            "true",
        )

    def test_capability_bootstrap_adds_operating_gate_after_all_market_gate(self) -> None:
        calls: list[str] = []

        def all_market(_values):
            calls.append("all-market")
            return True

        fake_bootstrap = SimpleNamespace(_enabled=lambda *_args, **_kwargs: False)
        fake = SimpleNamespace(
            memory_safe_managed_processes=lambda **_kwargs: (),
            _prequalify_release_evidence=all_market,
            _start_release_diagnostic_after_prequalification=lambda _values: None,
            render_bootstrap=fake_bootstrap,
        )

        def operating(_memory_safe, _values):
            calls.append("operating")
            return True

        with patch.object(
            capability_bootstrap,
            "prequalify_capability_operating_evidence",
            side_effect=operating,
        ):
            capability_bootstrap.install(fake)
            self.assertTrue(fake._prequalify_release_evidence({"RENDER": "true"}))

        self.assertEqual(calls, ["all-market", "operating"])


if __name__ == "__main__":
    unittest.main()
