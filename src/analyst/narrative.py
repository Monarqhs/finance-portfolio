"""Analyst narrative layer (optional, Gemini).

Implements docs/02-analysis-specs/05. Analyst Narrative (Gemini).md.

Composes module outputs into an analyst note, bounded by hard guardrails:
  - de-identified payload only (no real amounts / PII reaches the LLM);
  - a pre-send scrubber blocks the call if any real amount is detected;
  - post-generation banned-phrase and grounding checks;
  - a deterministic fallback so the LLM is never a dependency.

The LLM transport is injected (a callable), so tests use a mock and no network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# Predictive / instructional phrasing is not allowed in the narrative.
BANNED_PHRASES = (
    "will crash", "going to", "will fall", "will rise", "buy now", "sell now",
    "price target", "guaranteed", "is about to", "you should buy",
    "you should sell", "will pop",
)

# Detects a real currency amount (e.g. "Rp6.205.207", "$1,064", "USD 500").
_AMOUNT_RE = re.compile(
    r"(rp\s?\d[\d.,]*|\$\s?\d[\d.,]*|\busd\s?\d[\d.,]*|\bidr\s?\d[\d.,]*)",
    re.IGNORECASE,
)


@dataclass
class DeidentifiedPayload:
    """What the LLM is allowed to see: structure + percentages, no amounts."""

    positions: list[dict] = field(default_factory=list)  # label, kind, weight_pct, change_pct
    macro_tags: list[str] = field(default_factory=list)
    macro_evidence: list[str] = field(default_factory=list)  # percentage/bps facts
    concentration: dict = field(default_factory=dict)  # pct-only metrics
    opportunities: list[dict] = field(default_factory=list)
    headlines: list[str] = field(default_factory=list)

    def all_numbers(self) -> set[float]:
        """Every numeric value in the payload (for grounding), as floats so that
        '85' and '85.0' are treated as the same value."""
        text = " ".join([
            *(str(p) for p in self.positions),
            *self.macro_tags, *self.macro_evidence,
            str(self.concentration),
            *(str(o) for o in self.opportunities),
            *self.headlines,
        ])
        return {float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)}


@dataclass
class Narrative:
    text: str
    source: str  # "llm" | "deterministic-fallback"


def build_deidentified_payload(positions, macro, risk, opportunities, headlines=None):
    """Map rich module outputs to a de-identified payload.

    ``positions`` is a list of dicts already stripped to generic labels and
    percentages by the caller (the digest builder owns real amounts).
    """
    return DeidentifiedPayload(
        positions=positions,
        macro_tags=[t.code for t in macro.tags],
        macro_evidence=[t.evidence for t in macro.tags],
        concentration={
            "largest_sector_pct": round(risk.largest_sector_weight * 100, 1),
            "memory_factor_pct": round(risk.memory_factor_weight * 100, 1),
            "top1_pct": round(risk.top1_weight * 100, 1),
            "hhi": round(risk.hhi),
        },
        opportunities=[
            {"label": o.ticker, "score": o.total,
             "corr_to_semi": o.correlation_to_semi}
            for o in opportunities.ranked
        ],
        headlines=headlines or [],
    )


def contains_real_amount(payload: DeidentifiedPayload) -> bool:
    """Scrubber: True if any real currency amount leaked into the payload."""
    blob = " ".join([
        *(str(p) for p in payload.positions),
        *payload.macro_evidence,
        str(payload.concentration),
        *(str(o) for o in payload.opportunities),
        *payload.headlines,
    ])
    return _AMOUNT_RE.search(blob) is not None


def _has_banned_phrase(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in BANNED_PHRASES)


def _is_grounded(text: str, payload: DeidentifiedPayload) -> bool:
    """Every number in the narrative must appear in the payload (value-wise,
    so '85' matches a payload '85.0')."""
    allowed = payload.all_numbers()
    for num in re.findall(r"\d+(?:\.\d+)?", text):
        if float(num) not in allowed:
            return False
    return True


def deterministic_summary(payload: DeidentifiedPayload) -> str:
    """Rule-based narrative built from module outputs alone (no LLM)."""
    lines = ["Market read:"]
    if payload.macro_tags:
        lines.append("  Active regimes: " + ", ".join(payload.macro_tags) + ".")
    else:
        lines.append("  No notable macro regime shifts this week.")
    lines.append("Portfolio read:")
    c = payload.concentration
    if c:
        lines.append(
            f"  Largest sector {c.get('largest_sector_pct')}%, "
            f"memory factor {c.get('memory_factor_pct')}%, "
            f"top holding {c.get('top1_pct')}%, HHI {c.get('hhi')}."
        )
    lines.append("Concentration & opportunities:")
    if payload.opportunities:
        for o in payload.opportunities:
            corr = o.get("corr_to_semi")
            corr_s = "n/a" if corr is None else f"{corr:.2f}"
            lines.append(f"  {o['label']}: score {o['score']}, corr-to-semi {corr_s}.")
    else:
        lines.append("  No diversification candidates scored this week.")
    lines.append("Risks to watch: see the macro and risk sections below.")
    return "\n".join(lines)


def generate_narrative(
    payload: DeidentifiedPayload,
    llm_call: Callable[[str], str] | None,
    *,
    api_key: str | None = None,
) -> Narrative:
    """Produce the analyst note. Falls back to the deterministic summary on any
    privacy/guard failure, missing key, or LLM error.
    """
    # No key or no transport -> deterministic.
    if not api_key or llm_call is None:
        return Narrative(deterministic_summary(payload), "deterministic-fallback")

    # Privacy scrubber: never call the LLM if a real amount is present.
    if contains_real_amount(payload):
        return Narrative(deterministic_summary(payload), "deterministic-fallback")

    try:
        prompt = _build_prompt(payload)
        reply = llm_call(prompt)
    except Exception as exc:  # noqa: BLE001 - external call, stay fail-safe
        print(f"[narrative] LLM call failed ({type(exc).__name__}: {exc}) -> fallback")
        return Narrative(deterministic_summary(payload), "deterministic-fallback")

    if _has_banned_phrase(reply):
        print("[narrative] LLM reply contained a banned phrase -> fallback")
        return Narrative(deterministic_summary(payload), "deterministic-fallback")
    if not _is_grounded(reply, payload):
        print("[narrative] LLM reply had an ungrounded number -> fallback")
        return Narrative(deterministic_summary(payload), "deterministic-fallback")

    return Narrative(reply.strip(), "llm")


def _build_prompt(payload: DeidentifiedPayload) -> str:
    """System+task prompt pinning the analyst role and guardrails."""
    return (
        "You are a cautious investment analyst. Using ONLY the facts provided, "
        "write a concise note in four short sections: market read, portfolio "
        "read, concentration & opportunities, risks to watch. Attach a "
        "limitation to each claim. Never predict prices or returns, never say "
        "buy or sell, never invent numbers not present in the facts.\n\n"
        f"FACTS:\n{payload}"
    )
