"""The R3 prompt, built from the exception taxonomy rather than from the rows it will see.

**Why the taxonomy and not the data.** The obvious way to write this prompt is to look at the
credits the ladder could not clear and tune until each reads well. On this dataset that is four
rows, and tuning against four rows is fitting a prompt to a sample of four -- the same error as
a confidence threshold tuned until train looks good, wearing different clothes. The taxonomy is
the specification of what can go wrong; a prompt written from it covers cases this dataset does
not happen to contain, which is the whole point of writing it from the taxonomy.

So the prompt states every code, what it means, and what evidence distinguishes it. What it
does NOT contain is any description of a particular credit, seed or run.

No floats: this module is under src/ and the no-float scan covers it. Money reaches the model
as integer paise and comes back as settlement ids, never as a number the model computes.
"""

import hashlib
import json

# Codes the model may return. E03, E05, E10, E11, E12 are decided before R3 runs or cannot be
# seen at all, so offering them here would invite a code the engine then has to discard.
TAXONOMY = {
    "MATCH": "One or more settlements sum exactly to this credit. Name them.",
    "E01": "Money arrived that no settlement explains -- an unidentified receipt. The "
           "narration does not name the payment processor and no combination of settlements "
           "comes close to the amount.",
    "E02": "A settlement never reached the bank. Use this only if you are naming the "
           "settlement that is missing its credit.",
    "E04": "The narration identifies a settlement but the amount is wrong by more than a "
           "rupee. The money arrived; the figure disagrees.",
    "E13": "The credit is a real settlement but the narration cannot be read -- it does not "
           "name the processor and carries no usable reference.",
    "E14": "Two or more different combinations of settlements tie to this credit exactly and "
           "nothing in the narration picks one. Refuse: do not choose.",
}

INSTRUCTIONS = """\
You are helping a finance controller close the books for an Indian D2C merchant. Money moves
from customer payments, into settlement batches paid out by the payment processor, into credits
on the company's bank statement. Reconciliation means tying each bank credit to the settlements
inside it.

Deterministic rules have already run and cleared everything they could: exact reference match,
amount-and-date match within a one rupee tolerance, and exhaustive subset-sum over settlements
still open. What reaches you is what those could not settle.

Your job is TWO things, and the second matters more than the first:

1. If you can see a match the rules missed, propose it by naming settlement ids. Amounts are in
   integer paise. Do not compute or round anything -- name the ids and a deterministic
   validator will do the arithmetic. If your proposed settlements do not sum to the credit
   exactly, to the paisa, your proposal is rejected. Proposing loosely costs you nothing and
   gains nothing; it will simply be thrown away.

2. Explain the row to the controller. Assume they are competent, busy, and will act on what you
   write. Say what is wrong, what evidence you used, and what they should do next. One short
   paragraph, plain English, no hedging and no restating the numbers they can already see. If
   the honest answer is "this cannot be resolved from the available files", say that and say
   what file would resolve it.

Precision beats recall here. A wrong match hides a real problem and someone signs off on wrong
books. If the evidence does not single out one answer, return E14 and refuse -- refusing is a
correct answer, not a failure.

Return JSON only, matching this shape:
{"code": "<one of %s>",
 "settlement_ids": ["..."],
 "confidence": <integer 0-100>,
 "explanation": "<one paragraph for the controller>"}

`settlement_ids` is empty unless code is MATCH. `confidence` is your own estimate that your
answer is correct; it does not affect whether a proposal is accepted, and is recorded only so
we can measure whether stated confidence tracks being right.
"""


def _codes() -> str:
    return ", ".join(TAXONOMY)


def build(credit: dict, candidates: list[dict]) -> str:
    """The full prompt for one unresolved credit. Deterministic given its inputs.

    Candidates arrive sorted by the caller so the same credit always produces the same bytes;
    the cache is keyed on a hash of this string, and an unstable ordering would miss every time
    and call the API on every run.
    """
    lines = [INSTRUCTIONS % _codes(), "\nWHAT EACH CODE MEANS\n"]
    for code, meaning in TAXONOMY.items():
        lines.append(f"  {code}: {meaning}")
    lines.append("\nTHE BANK CREDIT\n")
    lines.append(f"  bank_ref:   {credit['bank_ref']}")
    lines.append(f"  date:       {credit['txn_date']}")
    lines.append(f"  amount:     {credit['credit_paise']} paise")
    lines.append(f"  narration:  {credit['narration']!r}")
    lines.append(f"\nSETTLEMENTS STILL OPEN ({len(candidates)}), any subset of which may sum "
                 f"to the credit\n")
    for s in candidates:
        lines.append(f"  {s['settlement_id']}  settled {s['settled_at']}  "
                     f"net {s['net_amount_paise']} paise  utr {s['utr']}")
    return "\n".join(lines) + "\n"


def key_for(prompt: str, model: str) -> str:
    """Cache key. The model is part of it: the same prompt to a different model is a different
    call, and silently reusing one provider's answer for another would make the two-provider
    comparison meaningless."""
    return hashlib.sha256(json.dumps({"p": prompt, "m": model}, sort_keys=True)
                          .encode("utf-8")).hexdigest()
