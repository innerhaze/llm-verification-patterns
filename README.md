# LLM verification patterns

Design notes on building a write path that uses a language model for per-record judgment without trusting any individual verdict. Written up from field experience on a data-quality pipeline that gates automated corrections against a shared production store.

The focus is the contract, not the model. The same pattern applies whether the reviewer is a frontier LLM, a smaller distilled model, or a committee of them.

## The problem

Per-record model judgment is useful on average and unreliable at the record level. A reviewer asked to decide "is this record correctly classified" produces outputs that are not wrong in aggregate but vary enough across runs that an operator cannot trust a specific decision without re-reviewing it. The variance is the problem, not the mean.

The outputs that caused the most trouble were not hallucinations in the dramatic sense. They were small, defensible-looking disagreements with the model's previous answer on the same input: a different threshold, a different reasoning path, a different confidence number. Over hundreds of records that is enough drift to make batch-level trust impossible.

## Why a confidence threshold does not fix this

The reflex is to filter: accept the record if the model's self-reported confidence exceeds some threshold, review the rest. This fails for two reasons.

First, confidence is itself a model output and inherits the same variance it was supposed to filter. The model reports 0.92 one run and 0.78 the next on the same input.

Second, the long tail of "wrong at high confidence" is exactly where this filter lets damage through. The confident mistakes are the ones that reach the shared store and have to be undone later.

A threshold is a dial on the same unreliable number. It does not add an independent signal.

## The three-layer contract

The pattern this write-up describes is a contract with three layers that
each produce an independent signal, and a write only lands when the three
agree. The shape of the contract is a composition of patterns that circulate
in the LLM-as-judge literature — reviewer, deterministic cross-check,
sampling eval — rather than something I claim to have invented. What I did
was implement it as the governing rule of a production write path, and
tune the sampling-audit threshold against measured concordance rather than
guesswork.

**Layer 1 — Reviewer.** The language model reads the record and returns a verdict with reasoning. This is the layer that handles judgement and natural language and nuance. It is allowed to be variable, because the two layers below decide whether to trust any given verdict.

**Layer 2 — Deterministic verifier.** A separate function re-derives the same decision from the numeric signals that fed the reviewer. If the two disagree, the record is routed to human review rather than auto-accepted. The verifier is not trying to be smarter than the reviewer. It is trying to be the same, from different inputs, so that a disagreement is a signal that one of them is wrong on this record.

**Layer 3 — Sampling audit.** A random sample from each batch is held aside. Both reviewer and verifier run on the sample as normal, and their agreement rate is measured. If concordance drops below a chosen bar (95% in the setup these notes come from), the whole batch is blocked rather than let through. The sampling layer catches drift at the batch level that the per-record layer cannot see.

The three layers answer three different failure modes. The reviewer catches cases the deterministic layer cannot articulate. The verifier catches cases the reviewer is confidently wrong on. The sampling audit catches runs where the reviewer has drifted enough that neither of the first two layers would notice on a single record.

## When to replace the model entirely with static rules

The reviewer does not need to run on every record. Known patterns — the specific defects the pipeline has seen before and already has a correct answer for — should be handled by a deterministic registry before the model ever sees the record.

In the pipeline these notes come from, that registry held two kinds of entry. Known miscategorisations: a specific chain whose records had been mis-tagged a particular way, and the rule for correcting it. Known false-positive patterns: a specific chain whose records had been incorrectly removed by an earlier filter, and the rule for restoring them. Pattern-matching records against those registries resolved them without an LLM call, which cut model budget and dropped variance on covered cases to zero (same input → same output).

The LLM only ran for cases the registry did not cover. A pattern that recurs enough to be hand-coded is a pattern the registry should own, not one the model should keep re-deriving.

The alternative that got rejected was prompt engineering: stronger system prompts, more few-shot examples. It had been tried and it worked for some patterns and failed for the long tail. A registry is deterministic by construction; prompt engineering is a bet that the next version of the prompt will generalise.

## Limits of the approach

A new pattern that the registry does not know about will still go through the reviewer, so the system can still be wrong on genuinely novel inputs. What it cannot be is inconsistent on patterns it has already seen. That trade-off is explicit and documented in the registries' own commit history.

The deterministic verifier is only as good as the signals it has access to. If the signals the reviewer uses are not available numerically, the verifier cannot re-derive the decision and the contract degrades to just the reviewer plus the sampling audit. That happened in a specific class of merge-collision cases — a shopping-centre record merging with its tenants — where the reviewer's judgement depended on text the verifier could not parse. In those cases the record went to human review by default.

The sampling audit's threshold is a judgement call. 95% concordance is defensible from "most records should match if the two layers are measuring the same thing", but it is not a universal number. In a domain where the deterministic layer is naturally weaker, 85% might be the operating point; in a domain where the two layers are near-identical, 99% is reasonable. The number has to come from measurement, not from the ceiling.

## Example

[`example.py`](example.py) implements the three-layer contract on a small synthetic dataset. A fake reviewer returns a verdict with a confidence number. A deterministic verifier re-derives the same decision from the record's numeric fields. The sampling audit holds back a random slice and computes concordance. The write path accepts a record only when reviewer and verifier agree, and blocks the whole batch when the sampling audit's concordance falls below 95%.

The example is deliberately small — a few dozen rows, a toy classifier — but the structure matches the production pattern.
