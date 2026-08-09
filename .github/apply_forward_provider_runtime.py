from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f"anchor count for {path}: {text.count(old)}")
    file.write_text(text.replace(old, new, 1))


replace_once(
    "production_paper_evidence.py",
    "from providers.alpaca_paper_resilient import create_complete_alpaca_paper_client\n",
    "from providers.alpaca_paper_resilient import create_complete_alpaca_paper_client\nfrom providers.forward_research import build_configured_forward_research_provider\n",
)
replace_once(
    "production_paper_evidence.py",
    '''    predictive = build_predictive_market_intelligence(\n        candidate=candidate,\n        features=features,\n        flow_observation=observation,\n        market=evidence.market,\n        existing_forward_intelligence=evidence.forward_intelligence,\n    )\n''',
    '''    forward_research_provider = getattr(\n        _FLOW_STATE, "forward_research_provider", None\n    )\n    research_evidence = (\n        None\n        if forward_research_provider is None\n        else forward_research_provider.fetch(candidate)\n    )\n    predictive = build_predictive_market_intelligence(\n        candidate=candidate,\n        features=features,\n        flow_observation=observation,\n        market=evidence.market,\n        existing_forward_intelligence=evidence.forward_intelligence,\n        research_evidence=research_evidence,\n    )\n''',
)
replace_once(
    "production_paper_evidence.py",
    '''def build_paper_evidence(*args, **kwargs):\n    _synchronize_runtime_bindings()\n    _FLOW_STATE.observations = {}\n    _FLOW_STATE.production_build = True\n    try:\n        return _ORIGINAL_BUILD_PAPER_EVIDENCE(*args, **kwargs)\n    finally:\n        _FLOW_STATE.production_build = False\n        _FLOW_STATE.observations = {}\n''',
    '''def build_paper_evidence(*args, **kwargs):\n    _synchronize_runtime_bindings()\n    _FLOW_STATE.observations = {}\n    _FLOW_STATE.forward_research_provider = (\n        build_configured_forward_research_provider()\n    )\n    _FLOW_STATE.production_build = True\n    try:\n        return _ORIGINAL_BUILD_PAPER_EVIDENCE(*args, **kwargs)\n    finally:\n        _FLOW_STATE.production_build = False\n        _FLOW_STATE.observations = {}\n        _FLOW_STATE.forward_research_provider = None\n''',
)
