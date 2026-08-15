"""Additional bounded parsers for global public macro and institutional evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from data.decision_information import DecisionInformationRecord
from providers.public_live_information import PublicLiveSourceDefinition
from providers.public_live_information_free_depth import (
    FreeDecisionDepthInformationProvider,
)


class GlobalDecisionDepthInformationProvider(FreeDecisionDepthInformationProvider):
    """Final public-information provider used by runtime evidence maintenance.

    Extending ``FreeDecisionDepthInformationProvider`` is deliberate: the runtime
    keeps the existing XBRL enrichment while adding the global macro parsers below.
    """

    def _parse_imf_datamapper(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        payload = response.json()
        if not isinstance(payload, Mapping):
            return []
        values = payload.get("values", {})
        if not isinstance(values, Mapping):
            return []
        output: list[DecisionInformationRecord] = []
        for indicator, geography_values in values.items():
            if not isinstance(geography_values, Mapping):
                continue
            for geography, observations in geography_values.items():
                if not isinstance(observations, Mapping):
                    continue
                for period, value in observations.items():
                    if value is None:
                        continue
                    item = {
                        "indicator": indicator,
                        "geography": geography,
                        "period": period,
                        "value": value,
                    }
                    output.append(
                        self._record(
                            source,
                            item,
                            retrieved_at=retrieved_at,
                            topic=f"IMF {indicator} observation",
                            summary=(
                                f"IMF {indicator} for {geography} was {value} "
                                f"for {period}."
                            ),
                            event_at=str(period),
                            published_at=retrieved_at,
                            source_identifier=(
                                f"imf-datamapper:{indicator}:{geography}:{period}"
                            ),
                            geographies=(str(geography),),
                            tags=(
                                "official-statistic",
                                "imf",
                                "global-macro",
                                str(indicator),
                            ),
                        )
                    )
        return output


__all__ = ["GlobalDecisionDepthInformationProvider"]
