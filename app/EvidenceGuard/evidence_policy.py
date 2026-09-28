"""Read the version-controlled Evidence Guard domain policy."""
from __future__ import annotations

from pathlib import Path


def domain_policy() -> tuple[set[str], list[str]]:
    """Return the hard denylist and trusted allowlist from the shipped policy."""
    policy = Path(__file__).with_name("docs") / "evidence-reputation.yaml"
    if not policy.exists():
        policy = Path(__file__).parents[2] / "docs" / "evidence-reputation.yaml"
    sections: dict[str, list[str]] = {"hard_denylist": [], "trusted_domain_allowlist": []}
    current: str | None = None
    for raw_line in policy.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.endswith(":"):
            current = line[:-1]
            continue
        if current in sections and line.startswith("- "):
            sections[current].append(line[2:].strip().lower())
    if not sections["hard_denylist"] or not sections["trusted_domain_allowlist"]:
        raise ValueError("Evidence reputation policy is incomplete.")
    return set(sections["hard_denylist"]), sections["trusted_domain_allowlist"]
