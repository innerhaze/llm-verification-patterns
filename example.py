"""Minimal illustration of the three-layer verification contract.

A toy classifier task: given a numeric signal and a textual note, decide
whether a record is 'accept' or 'reject'. The reviewer plays the role of
the language model (it is deliberately noisy, to make the point).
The deterministic verifier re-derives the decision from the numeric
signal alone. The sampling audit measures concordance across a random
slice before the batch is allowed through.

All data is synthetic.
"""

from __future__ import annotations

import dataclasses
import random
from typing import Literal

Verdict = Literal["accept", "reject"]


# ---------------------------------------------------------------------------
# A synthetic record. In a real pipeline this would be a point of interest,
# a product listing, a form submission, etc.
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class Record:
    record_id: int
    signal: float  # the numeric evidence (-1.0 .. 1.0)
    note: str  # a short textual field the reviewer reads

    @property
    def ground_truth(self) -> Verdict:
        return "accept" if self.signal >= 0.0 else "reject"


# ---------------------------------------------------------------------------
# Layer 1 — Reviewer (stand-in for an LLM).
#
# Produces a verdict with a confidence number. It is correct on average
# but noisy at the record level, which is the problem the contract exists
# to address.
# ---------------------------------------------------------------------------
def reviewer(record: Record, rng: random.Random) -> tuple[Verdict, float]:
    noise = rng.gauss(0.0, 0.12)
    perceived = record.signal + noise
    verdict: Verdict = "accept" if perceived >= 0.0 else "reject"
    confidence = min(1.0, max(0.0, 0.5 + abs(perceived) / 2.0))
    return verdict, confidence


# ---------------------------------------------------------------------------
# Layer 2 — Deterministic verifier.
#
# Re-derives the same decision from the numeric signal alone, by a rule
# the author can read. It is not trying to be smarter than the reviewer.
# It is trying to produce an independent answer that can be compared.
# ---------------------------------------------------------------------------
def verifier(record: Record) -> Verdict:
    return "accept" if record.signal >= 0.0 else "reject"


# ---------------------------------------------------------------------------
# The per-record contract: both layers must agree.
# Disagreement does not mean the reviewer was wrong. It means the record
# is routed to human review rather than written to the shared store.
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class RecordDecision:
    record_id: int
    reviewer_verdict: Verdict
    verifier_verdict: Verdict
    reviewer_confidence: float
    outcome: Literal["auto_accept", "human_review"]


def decide(record: Record, rng: random.Random) -> RecordDecision:
    rv, conf = reviewer(record, rng)
    vv = verifier(record)
    outcome = "auto_accept" if rv == vv else "human_review"
    return RecordDecision(
        record_id=record.record_id,
        reviewer_verdict=rv,
        verifier_verdict=vv,
        reviewer_confidence=conf,
        outcome=outcome,
    )


# ---------------------------------------------------------------------------
# Layer 3 — Sampling audit.
#
# A random sample is held aside and the two layers are run on it as normal.
# If the concordance rate (fraction of records where both agree) falls
# below the threshold, the whole batch is blocked.
# ---------------------------------------------------------------------------
def sampling_audit(
    records: list[Record],
    rng: random.Random,
    sample_size: int = 50,
    threshold: float = 0.95,
) -> tuple[float, bool]:
    sample = rng.sample(records, k=min(sample_size, len(records)))
    agreements = 0
    for r in sample:
        rv, _ = reviewer(r, rng)
        vv = verifier(r)
        if rv == vv:
            agreements += 1
    concordance = agreements / len(sample)
    allowed = concordance >= threshold
    return concordance, allowed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    rng = random.Random(42)
    records = [
        Record(record_id=i, signal=rng.uniform(-1.0, 1.0), note=f"item {i}")
        for i in range(300)
    ]

    concordance, allowed = sampling_audit(records, rng)
    print(f"sampling audit concordance: {concordance:.2%}")
    if not allowed:
        print("BLOCKED: batch does not meet 95% concordance threshold")
        return

    decisions = [decide(r, rng) for r in records]
    auto = sum(1 for d in decisions if d.outcome == "auto_accept")
    human = len(decisions) - auto
    print(f"auto_accept: {auto}  human_review: {human}")

    # Of the auto-accepts, how many actually match ground truth?
    gt_matches = sum(
        1
        for d, r in zip(decisions, records)
        if d.outcome == "auto_accept" and d.reviewer_verdict == r.ground_truth
    )
    if auto:
        print(f"auto_accept agreement with ground truth: {gt_matches}/{auto}")


if __name__ == "__main__":
    main()
