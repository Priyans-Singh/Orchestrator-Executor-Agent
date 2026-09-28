#!/usr/bin/env python3
"""Validate the declarative frozen-evaluation contract without AWS access."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "agentcore" / "agentcore.json"
FIXTURE = ROOT / "evaluators" / "fixtures" / "frozen-eval-sheet" / "Performance.csv"
DATASETS = (
    ROOT / "evaluators" / "datasets" / "frozen-eval-predefined.json",
    ROOT / "evaluators" / "datasets" / "frozen-eval-simulated.json",
)
CODE_EVALUATORS = {
    "DataBoundaryViolation": "TRACE",
    "SecurityGuardrailViolation": "TRACE",
    "CitationLinkIntegrity": "SESSION",
    "EnvelopeSchemaConformance": "TRACE",
    "DelegationOrderingTrajectory": "SESSION",
    "BestEffortConfirmationGating": "TRACE",
}
JUDGE_EVALUATORS = {
    "PromptInjectionResistance": "TRACE",
    "DiagnosticAccuracy": "SESSION",
    "EvidenceCitationRelevance": "TRACE",
}
REQUIRED_ASSERTIONS = {"data_boundary", "security_guardrail", "best_effort_confirmation"}


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> None:
    config = json.loads(CONFIG.read_text())
    evaluators = {item["name"]: item for item in config["evaluators"]}
    check(set(evaluators) == set(CODE_EVALUATORS | JUDGE_EVALUATORS), "expected exactly nine baseline evaluators")

    for name, level in CODE_EVALUATORS.items():
        evaluator = evaluators[name]
        check(evaluator["level"] == level, f"{name} has the wrong level")
        check("codeBased" in evaluator["config"], f"{name} must be code-based")
    for name, level in JUDGE_EVALUATORS.items():
        evaluator = evaluators[name]
        check(evaluator["level"] == level, f"{name} has the wrong level")
        judge = evaluator["config"].get("llmAsAJudge")
        check(judge is not None, f"{name} must be LLM-as-a-judge")
        labels = [item["label"] for item in judge["ratingScale"]["categorical"]]
        check(labels == ["Pass", "Partial", "Fail"], f"{name} must use Pass/Partial/Fail")

    agent_models = {
        re.search(r'^MODEL_ID = "([^"]+)"$', (ROOT / "app" / agent / "model" / "load.py").read_text(), re.MULTILINE).group(1)
        for agent in ("OrchestratorAgent", "DiagnosticAgent", "EvidenceGuard")
    }
    check(len(agent_models) == 1, "agents must agree on the shared Bedrock judge model")
    check({evaluators[name]["config"]["llmAsAJudge"]["model"] for name in JUDGE_EVALUATORS} == agent_models, "judges must reuse the agents' shared Bedrock model")

    online = config["onlineEvalConfigs"]
    check(len(online) == 1, "expected one production online-eval config")
    check(set(online[0]["evaluators"]) == {"DataBoundaryViolation", "SecurityGuardrailViolation", "PromptInjectionResistance"}, "online eval must contain only dimensions 1, 2, and 7")

    with FIXTURE.open(newline="") as fixture_file:
        rows = list(csv.DictReader(fixture_file))
        check(tuple(rows[0]) == ("date", "revenue", "segment", "orders"), "fixture columns must match the data contract")
        check(len(rows) > 0, "fixture must contain synthetic rows")

    for dataset_path in DATASETS:
        dataset = json.loads(dataset_path.read_text())
        check(dataset["fixture"] == "frozen-eval-sheet", f"{dataset_path.name} must use the frozen fixture")
        for scenario in dataset["scenarios"]:
            check("expected_response" in scenario, f"{scenario['id']} lacks expected_response")
            check("expected_trajectory" in scenario, f"{scenario['id']} lacks expected_trajectory")
            assertions = scenario.get("assertions", {})
            check(REQUIRED_ASSERTIONS <= assertions.keys(), f"{scenario['id']} lacks required per-scenario assertions")

    simulated = json.loads(DATASETS[1].read_text())["scenarios"]
    ids = {scenario["id"] for scenario in simulated}
    check("clarification-round-trip" in ids, "simulated clarification coverage is missing")
    check("prompt-injection-is-resisted" in ids, "simulated prompt-injection coverage is missing")


if __name__ == "__main__":
    main()
