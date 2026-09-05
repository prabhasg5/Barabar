# Barabar — Product Requirements

Settlement reconciliation for Indian D2C merchants.
Submission for the Razorpay AI Buildathon, Track 04 (AI Finance Controller).

**The name.** *Barabar* means equal, level, even — two sides that come out the same. "Hisaab barabar" is the everyday phrase for accounts settled. The name is also the interface: the product's signature element is two bars that must end level, and the gap between them is the finding. Product copy is English throughout; only the name is Hindi.

---

## 1. The problem

A merchant sells 340 items in a day. Money does not arrive as 340 payments. It arrives as **one bank credit** — say ₹4,32,187.55 — because the payment aggregator nets everything: payments, minus fees, minus GST on fees, minus refunds, minus chargebacks, minus adjustments.

The merchant cannot answer the only question that matters: **is that number right?**

Today the answer is a finance executive with three spreadsheets and VLOOKUP, two to three days a month, who eventually gives up and accepts the number. Discrepancies — fee overcharges, missing settlements, unlinked refunds — go unfound because nobody has time to look.

**Who this is for:** the finance executive (or the founder's CA) at a D2C brand doing 150–400 orders/day on Razorpay. One person. Once a month. Under time pressure.

**Their job:** close the month, and be able to defend the close.

---

## 2. What we build

A tool that ingests five files, ties the lump sums back to the orders inside them, and produces a close summary plus a short, explained list of everything that did not tie.

**The output that matters is not the 96% that matched. It is the 4% that did not, explained well enough to act on in under a minute each — plus a rupee figure for money the merchant lost without knowing.**

---

## 3. Scope

### In scope
- Ingest: orders, payments, refunds, settlements, bank statement (CSV)
- Three-level tie: order ↔ payment ↔ settlement batch ↔ bank credit
- A four-rung matching ladder, cheap methods before expensive ones
- Exception classification into a fixed taxonomy
- Plain-English explanation for every exception
- Fee and GST variance audit against the contracted rate
- Human review queue for the tail, with decisions remembered
- Close summary with reconciled %, ₹ open, ₹ discrepancy found
- Evaluation harness reporting measured accuracy on held-out synthetic data
- Synthetic data generator producing realistic, messy, labelled data

### Out of scope — do not build these
- Cash flow forecasting
- Tax line matching
- Chat / conversational interface
- Multi-user, roles, auth, tenancy
- Charts, graphs, dashboards, "insights"
- Live Razorpay API integration (synthetic + test-mode data only)
- Mobile app
- Export to Tally / Zoho / QuickBooks

Every hour spent on the out-of-scope list is an hour not spent on the eval harness, which is the only thing that separates this from the median submission.

---

## 4. Data

### Inputs (CSV)

**orders.csv** — `order_id, created_at, customer_ref, customer_name, pincode, gross_amount_paise, status`

**payments.csv** — `payment_id, order_id, captured_at, amount_paise, method, fee_paise, gst_paise, settlement_id, status`

**refunds.csv** — `refund_id, payment_id, created_at, amount_paise, type, settlement_id, status`

`type` is `refund` or `chargeback`. One file for both because they are the same shape and differ only in direction of blame. `payment_id` may be blank — that is exactly the E08/E09 case and must survive ingest as an exception, not a rejected row.

**`amount_paise` is a positive magnitude.** The direction is carried by `type`, never by the sign, and the identity in §8 subtracts it. A negative value here is a malformed row and is rejected. This is stated because the alternative convention — signed amounts — is equally defensible and picking it silently at ingest time is how a refund ends up added to a settlement.

**settlements.csv** — `settlement_id, settled_at, utr, net_amount_paise, fee_paise, gst_paise, refund_paise, adjustment_paise`

`refund_paise` here is the batch aggregate. It must equal the sum of `refunds.csv` rows carrying that `settlement_id`; when it does not, that is the finding.

**bank_statement.csv** — `txn_date, narration, credit_paise, debit_paise, closing_balance_paise, bank_ref`

### Rules
- **All money is integer paise.** No floats anywhere in the codebase, including intermediate calculations. Format to rupees only at the render boundary.
- Bank narration is a raw machine string and must be treated as unreliable: `NEFT-RAZORPAY SOFTWARE PRIVA-UTR123456789-HDFC-XXXXX`
- Dates in inputs are inconsistent by design (`DD/MM/YYYY`, `YYYY-MM-DD`, `DD-Mon-YY`). Normalise at ingest.
- Reject malformed rows loudly with row number and reason. Never silently skip a row — a reconciler that drops records is worse than no reconciler.
- **Ingest reports every bad row in one pass and then loads nothing.** Not first-error-and-stop, which makes fixing a file an N-round trip; not load-the-good-ones, which produces a confident close that is wrong by however many rows were dropped.
- **Ingest rejects rows it cannot read. It never rejects a row that merely looks wrong.** A payment with no order, a refund with no payment, a payment in no settlement batch — those are E06, E08 and E02, which is to say they are the findings. Only unreadable data is refused: a missing amount, a decimal point in a paise column, a date in no known format, an unknown payment method, a repeated id.

---

## 5. The matching ladder

Four rungs, tried in order. Each rung records which records it cleared so contribution can be attributed.

| Rung | Method | Uses LLM | Target clear |
|---|---|---|---|
| **R0** | Exact: UTR match + amount equal to the paisa | No | ~70% |
| **R1** | Composite: amount + date window + partial reference | No | ~15% |
| **R2** | Combination: which subset of **settlements** sums to this credit | No | ~10% |
| **R3** | LLM: narration parsing, entity resolution, explanation | Yes | ~5% |

**These four percentages are a generator target, not a measurement.** The rung split is set by
the structure of the data — how often a credit bundles several settlements, and how often the
UTR is recoverable from the narration — so it is something the generator decides and `EVAL.md`
reports. `EVAL.md` prints what actually came out, next to this table, and explains any gap.

### R2 is worth building properly

"Which subset of these settlements sums to ₹4,32,187.55?" is a subset-sum problem. Solve it
algorithmically — meet-in-the-middle, or DP over a bounded candidate window — not with the LLM.
The model would be slower, non-deterministic, and worse. Building this deterministically and
saying so is a deliberate signal about AI judgment.

**Bound the pool before solving it.** Ambiguity is primarily a filter problem, not a solver
problem. Re-measured on the current data at the window §5 derives, both seeds: with no date
filter, 2 of 8 train bundles and 1 of 6 held-out admit more than one exact subset; with the
window on, 1 and 1 — and the one that remains on each seed is the engineered decoy, which is
built to sit inside the window. *(train+heldout, 6b, 2026-09-01)* Same solver, same tolerance; the only thing that changed was
how many settlements sat in the pool. Filter by date window and amount ceiling first, then
solve over what remains.

The figure this paragraph carried until 6b was "6 of 8 unfiltered, zero filtered". It was
measured before 6a, at a window of ±5 and a subset size of 2–4, on data that has since been
regenerated twice, and it was quoted forward across both regenerations without being re-run.
Both halves were wrong by the end: unfiltered is 2, and filtered is 1 rather than zero because
6b's decoy is deliberately in-window. **A measurement is pinned to the data it was taken on;
quoting it after a regeneration measures the regeneration.**

**The pool is what is still unclaimed, and that is not a detail.** A settlement already tied to
its own bank credit by R0 or R1 cannot also be a member of a different credit — §14's
partition rule requires every settlement to end in exactly one state. So R2 enumerates over
open settlements only, and a rival subset exists only if its members are still open when R2
runs. Ambiguity is a property of what survives the ladder, not of the arithmetic alone.

**R2 gets its own parameters, separate from R0/R1.** It has combinatorially more chances to land
on a plausible-looking sum than a rung matching a single settlement, so it gets stricter
settings. **Each is derived from how the data is constructed, not read off one dataset.**
Both of these lines were originally fitted to `SEED_TRAIN` and both were then contradicted by
held-out — a window of ±5 and a subset size of 2–4 are exactly what train's largest bundle
(size 4, spanning exactly 5 days) produces. A derivation predicts the size-5 case; an
observation of train cannot:

| Parameter | Value | Why |
|---|---|---|
| Tolerance | **0 paise — exact** | Every paisa of slack is a window that any of thousands of subsets can fall into. A bundle that ties only within tolerance is an exception, not a match. |
| Date window | **±6 days** | Derived, not observed. A size-N bundle spans N−1 settlement gaps; settlements land on business days, so one weekend inside those gaps adds two calendar days. A size-5 bundle therefore reaches 6 days from its credit and no further: 4 + 2. Observed maxima agree exactly — size 2 → 3 days, size 4 → 5, size 5 → 6 *(train+heldout, 6b, 2026-08-29)*. The derivation is what the value rests on; the observation is a check on it, and if a regeneration moves it the derivation is what gets re-examined. |
| Subset size | **2–5** | Derived from §8's declared `bundle_size` of [2, 5], not from what one dataset happened to contain. The solver's range must be the generator's range or real matches are unsolvable by specification. The combinatorial cost is nil: the window leaves 2–6 spare settlements, so allowing size 5 adds a handful of subsets. |

`DATE_WINDOW_DAYS` is therefore per-rung, not module-level. R0 and R1 keep ±2.

### The safety rule
> **The LLM proposes. Deterministic code disposes.**

R3 emits a *candidate* match with a confidence and a rationale. A deterministic validator re-checks the arithmetic. If the amounts do not tie to the paisa, the candidate is rejected regardless of stated confidence. **The LLM never writes a match directly.** State this verbatim in the architecture notes.

**There is no confidence threshold.** The validator is binary and exact, so a threshold could
only discard proposals before a free check — it would buy nothing and could only lose true
matches. Confidence is logged and its correlation with validation reported, as a measurement.

**Tying is necessary and not sufficient**: a credit R2 refused as E14 is never offered to R3,
because a proposal that ties is not evidence the model found the only subset that does. See
`ARCHITECTURE.md`.

**Provider: Google AI Studio (Gemini Flash), with Groq-hosted Llama as a second run behind the
same interface.** Two providers on the same prompts is how we show the *validator* is doing the
work rather than the model — one provider agreeing with itself proves nothing. The interface is
`call(prompt, provider) -> (text, prompt_tokens, completion_tokens)` and nothing provider-shaped
crosses it. Keys come from `.env`, which is gitignored; `.env.example` is committed.

### Tolerance

**Tolerance is 100 paise (₹1.00) absolute, per match, whole-match — not per record inside it.** It is not a percentage, and it does not scale with the amount: ₹1 of rounding drift on a ₹4 lakh credit is the same ₹1 as on a ₹400 one.

Tolerance exists for one reason: rounding drift. It is never spent to absorb a fee difference, a missing refund, or a partial settlement. Those are findings.

- Match ties to the paisa → matched, clean.
- Match ties within 100 paise → matched, flagged **E03**, delta recorded.
- Outside 100 paise → not a match. **E04**.

**R2 spends no tolerance at all.** A bundle matches on an exact tie or not at all, for the reason in the parameter table above.

**And exactness alone is not enough — the solution must also be unique.** If two or more distinct subsets tie exactly, the solver returns no match and raises **E14**. It counts solutions, stops at two, and gives up. This uniqueness check is the precision guard for the whole rung.

Before giving up, R2 may apply only *evidence-based* discriminators:

- A partial UTR in the narration matching a settlement in one subset and not in the other.

It may not apply heuristics — not "fewer settlements is more likely", not "prefer earlier dates", not "prefer the subset that leaves fewer orphans". Those are guesses wearing the costume of logic, and each one trades precision for a recall point that was never really earned.

Any match that consumes tolerance is flagged, and total absorbed drift is reported at the end of every run. Silently absorbing ₹0.50 four thousand times is ₹2,000 invented from nothing. If absorbed drift for a run exceeds ₹100, the run says so at the top of the summary rather than in a footnote.

### Precision over recall
In reconciliation, a false match is worse than no match, because it **hides a real break** and someone signs off on wrong books. Target near-100% precision on auto-matches; trade recall to get it. Say this explicitly in the UI and the docs.

---

## 6. Exception taxonomy

Fixed codes so runs are comparable month to month. **Fourteen codes, all of which the generator
produces and the eval scores.** A code with no test data is a code that is wrong in production
and never fails a test, so nothing sits in this table that the generator cannot make.

E14 was originally a currency/FX code and was deleted — a rupee-only D2C merchant has no FX
line. The number is reused for ambiguity, which is a state the engine genuinely reaches.

**Two kinds of exception, and the difference matters to the user.** `is_break` distinguishes them:

- **A break** means something is wrong with the money. Investigate it.
- **An ambiguity** means nothing is wrong. The evidence simply does not single out one answer, and a human can usually settle it in seconds by answering one question.

Burying a question inside a list of problems wastes the controller's attention on the pile that actually needs judgement.

| Code | is_break | Meaning |
|---|---|---|
| E01 | true | Bank credit with no matching settlement (unidentified receipt) |
| E02 | true | Settlement with no bank credit (in transit or missing) |
| E03 | true | Amount mismatch within tolerance — matched, flagged |
| E04 | true | Amount mismatch outside tolerance — break |
| E05 | true | Fee variance vs contracted rate |
| E06 | true | Payment with no order (orphan) |
| E07 | true | Order claims paid, no payment exists |
| E08 | true | Refund not linked to an original payment |
| E09 | true | Chargeback debit absent from orders |
| E10 | true | Duplicate payment against the same order |
| E11 | true | Partial refund drift — **undetectable by design from these sources; see below** |
| E12 | true | Period cutoff (paid in month M, settled in M+1) |
| E13 | true | Unparseable narration |
| **E14** | **false** | **Ambiguous bundle — two or more subsets of settlements tie exactly to this credit. Nothing is wrong with the money; the evidence does not single out one answer.** |

**E11 is in this table and cannot be raised, and that is deliberate.** A refund that settles
short reduces the refund row and the settlement's refund total by the same figure, so every
file stays internally consistent and nothing anywhere records what the refund was originally
raised for. It is undetectable from orders, payments, refunds, settlements and a bank
statement — not by an oversight in the classifier but by the shape of the inputs. Measured at
0 of 64 settlements showing any inconsistency with 33–35 partial refunds present
*(train+heldout, 6b, 2026-09-01)*.

The code stays in the taxonomy anyway. **A taxonomy trimmed to what the engine catches reports
a clean run on books that are short.** The rule in this section is that nothing sits here the
generator cannot make; the converse — that everything here must be detectable — is not a rule
and must not become one by attrition. E11 is marked undetectable, the reason is stated, and
the classifier's `known_gaps()` declares it in code so it reads as a blind spot rather than as
zero occurrences. A merchant who needs it needs a fourth source: the refund authorisation,
carrying the amount requested as distinct from the amount settled. That is out of scope, and
saying so is more useful than silence.

Every exception row carries: code, both record ids, the rupee delta, the rung that gave up, and a one-sentence plain-English reason.

**E14 additionally carries every candidate subset**, not just a count. The exception is only actionable if the reviewer can see what the choices were.

---

## 7. The fee variance audit

This is the feature that turns a match rate into a rupee number, and the reason a merchant would actually install this.

**Rates are integers in basis points. There is no float in this calculation** — a rate of `0.02` is a float in a money path and hard rule 1 forbids it. Round half up with integer arithmetic:

```
expected_fee = mul_bps(amount_paise, fee_bps)
expected_gst = mul_bps(expected_fee, gst_bps)
```

`mul_bps` rounds half **away from zero**, and applies the sign after the division. Plain
`(amount * bps + 5000) // 10000` floors, so it returns 0 where a refund of -100 paise at
200 bps owes -2 — every negative amount in the book would silently under-reverse.

The rate is **per method**, because a flat rate makes every UPI payment look like a variance and buries the real findings in noise:

```
fee_bps = {"upi": 0, "card": 200, "netbanking": 190, "wallet": 220}
gst_bps = 1800          # on the fee, not on the payment
```

**The method set is closed:** `upi | card | netbanking | wallet`. A payment carrying anything else is rejected at ingest with its row number, not defaulted to a rate. A missing key here would either crash the audit mid-run or, worse, quietly bill 0 bps and report no variance on a whole payment method.

That dict is the contract. It is a module-level constant, not a config system — it moves to config when a second merchant exists.

The generator applies its own copy of a rate card and injects contract-vs-actual discrepancies against it; the auditor must not import the generator's copy.

Compare to actual. Every mismatch is a rupee-denominated finding. Aggregate into a headline of
the shape **"₹8,412 in fee overcharges across 214 payments this period"** — *that figure is an
illustration of the sentence, not a measurement, and must not be quoted as one.* Measured on
this data: ₹195.18 overcharged across 40 payments on train, ₹177.09 across 37 on held-out
*(train+heldout, 6b, 2026-09-01)*.

**Report overcharged and undercharged separately, and the net third.** An aggregator
misconfigures in both directions and so does the generator, so a single net figure lets an
overcharge and an undercharge cancel into "no finding" — the same cancellation that makes a
sum-over-a-population a weak assertion (see §14). On train the net understates the overcharge
by ₹82.77.

### The second number: fee paid on refunded revenue

**MDR is not reversed on refunds in India.** The gateway keeps the fee whether or not the sale
survives, so every refunded payment's fee and GST are permanently spent on revenue the merchant
gave back. Measured: ₹2,347.48 across 172 joined refunds on train, ₹2,536.59 across 179 on
held-out *(train+heldout, 6b, 2026-09-01)* — roughly nine times the variance figure.

**It is reported separately and carries no exception code.** A variance is an error to dispute;
this is a correct charge on cancelled revenue. There is nothing to fix and nobody to argue
with. Giving it a code would put it in the exception list beside things that are wrong and
spend a controller's investigation on a correct charge. It earns its place because it is a real
cost that appears in no statement as a line item — nothing to fix, only to see.

Counted only over refunds that join to a payment; an unlinked refund (E08/E09) has no fee to
attribute.

---

## 8. Synthetic data generator

### Anti-circularity requirement
The generator writes a ground-truth file that **the matching engine never reads**. Separate module, separate directory, loaded only by the eval harness. Say this in one line in the README — it pre-empts the obvious reviewer objection that you generated data from rules and then rediscovered your own rules.

### Ground truth file

Written by `src/generate/`, read only by `eval/`. The engine never opens it — asserted in a test.

```jsonc
{
  "seed": 42,
  "matches": [                       // the answer key for the ladder
    {"bank_ref": "...", "settlement_ids": ["..."], "payment_ids": ["..."]}
  ],
  "breaks": [                        // the answer key for the taxonomy
    {"record_type": "payment", "record_id": "pay_...", "code": "E05", "delta_paise": -1240}
  ],
  "ambiguous": [                     // the answer key for E14
    {"bank_ref": "...", "true_subset": ["setl_..."], "decoy_subsets": [["setl_...", "..."]]}
  ],
  "expected_fees": {                 // the answer key for the audit
    "pay_...": {"fee_paise": 1200, "gst_paise": 216}
  },
  "totals": {"gross_paise": 0, "fee_paise": 0, "gst_paise": 0,
             "refund_paise": 0, "adjustment_paise": 0,
             "credit_paise": 0, "in_transit_paise": 0}
}
```

A match is scored as a whole: the engine's `payment_ids` set must equal the ground-truth set exactly. Four of five payments right is one false positive, not four true positives — this is the unit for both precision and recall, and it is the reason the numbers in §12 mean anything.

**An `ambiguous` entry is scored as a refusal, not a match.** The correct engine behaviour is to
emit E14 listing every candidate. Picking the `true_subset` counts as a **false** match even
though the subset happens to be right, because the engine had no evidence to justify choosing it
and would have been wrong as often as not on data the generator did not label. Guessing
correctly is not the same as knowing, and a scoring rule that rewards the guess would teach the
solver to guess.

`totals` exists so the eval can assert the conservation identity, which is the invariant everything else rests on. Note the sign on adjustments — they are **signed** and therefore added; they run both ways, and subtracting them would silently double every credit adjustment:

```
Σ gross − Σ fee − Σ gst − Σ refund + Σ adjustment − in_transit  ==  Σ credit + ₹open
```

### Scale
5,000 payments across ~60 settlement batches over 3 months. The brief asks for 50+ records; delivering 100× that is the cheapest way to clear the throughput bar.

### Structural knobs — these set the rung split

Break rates do not decide how hard the data is to match. Three structural facts do, and all
three are named parameters recorded in `ground_truth.json`:

```
credit bundles > 1 settlement    12%      (2–5 settlements per bundled credit)
UTR in narration                 78% verbatim / 12% truncated / 6% garbled / 4% absent
bundled credit has a decoy       every one that admits a construction — 1 per seed at
                                 this scale (see below). Not a rate, and not 30%.
```

Bundling is the only reason R2 exists. UTR recoverability is the whole of the R0/R1/R3
boundary. Decoys are the only reason E14 can be scored. Stating them as parameters is what lets
§12's rung attribution be read as a consequence of a declared distribution rather than presented
as a discovery.

**The decoy knob is a count, not a rate, and that is a finding rather than a shortcut.** It was
declared at 30% of bundled credits. A decoy needs a rival subset built from settlements that
survive to R2 — see below — and at 5,000 payments over three months the ±6 day window offers
one on a single bundle per seed: 1 of 8 on train, 1 of 6 on held-out *(train+heldout, 6b, 2026-09-01)*. The generator therefore
attempts every bundled credit and builds wherever a construction exists, and `EVAL.md` reports
the count it got. Quoting 30% would be holding a number the data does not support; one real E14
per seed is worth more than two that the ladder dissolves before the solver sees them.

### Decoy bundles — the E14 path

A decoy is a second subset of settlements that ties **exactly** to a bundled credit's amount, so
the solver finds two valid answers and must refuse.

**Constructed in `world.py` at build time, not injected by `breaks.py`.** A decoy is a fact about
how the world is shaped, like bundling — not damage done to a clean world. And because R2's
tolerance is zero, a decoy has to tie to the paisa, which cannot be achieved by mutating
settlement amounts after the fact without breaking those settlements' own arithmetic. The
generator must instead choose the contents of the decoy settlements as it builds them, so every
constituent payment, fee and refund still ties.

**A rival subset must survive the ladder, or it is not a rival.** This is the constraint that
decides the whole construction, and it is easy to miss: a decoy built from settlements that each
carry their own bank credit is arithmetically perfect and completely inert, because R0 or R1
claims every one of them against its own credit before R2 ever runs. The solver then finds a
single answer, matches it, and the answer key is left claiming an ambiguity the data no longer
holds. Decoy members must therefore come from the settlements that reach R2: those inside
*other* bundled credits, which no single-settlement rung can claim, or those in transit, which
have no credit to be claimed against.

Decoy settlements must also fall inside R2's window and subset size. Outside either, they are
filtered out before the solver runs and test nothing.

**The target credit must give up its UTR.** §5 permits R2 to use a reference naming a settlement
in one subset as evidence, and a bundled credit's narration carries a true-subset member's UTR
by construction — so the evidence would resolve the tie and the credit is not ambiguous at all.
An ambiguity the evidence settles is not an E14.

**Why this is generated rather than fixtured.** The tool is built for real merchant data, and at
real volume this is not a rare coincidence. The number of candidate subsets grows
combinatorially with the number of settlements inside the date window, so a merchant running
several settlement cycles a day has orders of magnitude more chances to collide than this dataset
does. A path exercised only by a hand-written fixture is a path whose real-world rate is unknown.

**Honest reporting requirement.** This yields **one** E14 case per run — enough to prove the path
works, far too few to be a sample. `EVAL.md` must report it as a count with its denominator
(1 of 6 bundled credits on held-out, 1 of 8 on train — *train+heldout, 6b, 2026-09-01*) and say plainly that no ambiguity *rate*
can be claimed from it.

### Break injection, with a documented distribution
```
timing cutoff           emergent, ~3%   (see below)
fee variance            1.5%   (both over and under)
partial refund          2.0%
unparseable narration   1.0%
duplicate payment       0.8%
missing settlement      0.5%
unidentified receipt    0.3%   E01
payment with no order   0.3%   E06
paid order, no payment  0.3%   E07
unlinked refund         0.2%   E08
unlinked chargeback     0.2%   E09
rounding drift          every ~20th record, ±₹0.01–0.50
```

E14 is not in this list. It is structural, built in `world.py`, and labelled at construction —
see the decoy section above.

**E07 is qualified: only orders whose `status` claims paid.** An order with no payment and no
claim to have been paid is an abandoned cart, which is the single most common row in D2C order
data and not an exception. Flagging those would bury the real E07s under thousands of them.

**Timing cutoff (E12) is not injected, it is labelled.** Payments captured in month M whose
batch settles in M+1 arise naturally from T+2 settlement across a month boundary. The generator
knows which ones they are at construction time and labels them there. The rate is therefore
emergent, and `EVAL.md` reports the count that actually occurred.

### Seeds and held-out discipline

Two named seeds, both recorded in `ground_truth.json`:

```
SEED_TRAIN     = 20260101      development, tuning, debugging -- look at it as often as you like
SEED_HELDOUT   = 20260331      opened at four moments only
```

`SEED_HELDOUT` results are looked at at **steps 5, 6, 9 and 13** of §15 and nowhere else:

| Step | Moment |
|---|---|
| 5 | Eval harness — first number on the board |
| 6 | R2 combination solver — the deterministic delta |
| 9 | R3 LLM rung — the model's marginal delta |
| 13 | Final `EVAL.md` |

Every other run uses `SEED_TRAIN`. This costs nothing and it is the difference between
"held-out" as a claim and "held-out" as a fact — a held-out set consulted on every iteration is
a training set with a misleading name.

Realism requirements: Indian names and pincodes, real bank narration formats, mixed date formats, UPI/card/netbanking method split roughly matching Indian e-commerce, weekend settlement gaps, month-end volume spikes.

---

## 9. Screens

Three. If a fourth is tempting, it is fluff.

### 9.1 Close summary

The landing screen after a run. Answers "can I sign off?" in five seconds.

*Illustrative layout — every figure below is invented for the mockup, not measured.
No number in this block may be quoted as a result.*

```
┌──────────────────────────────────────────────────────┐
│  MAR 2026 CLOSE                     [ Run again ]    │
│                                                      │
│  ₹68,42,100 reconciled                    96.2%      │
│                                                      │
│  expected  ████████████████████████████████████┊     │
│  received  ██████████████████████████████▒▒▒▒▒▒┊     │
│                                    ₹2,84,000 short   │
│                                                      │
│  40 breaks · ₹2,71,000     2 questions · ₹13,000     │
│  ₹8,412 in fee overcharges found                     │
│                                                      │
│  ── how it was matched ──────────────────────────    │
│  R0  exact              3,514   70.3%                │
│  R1  composite            762   15.2%                │
│  R2  combination          498    9.9%                │
│  R3  assisted             184    3.7%                │
│                                                      │
│  precision 99.97%  ·  drift absorbed ₹4.20           │
│  run took 41s  ·  ₹18 in model cost                  │
└──────────────────────────────────────────────────────┘
```

Breaks and questions are counted separately, per `is_break` in §6. A controller triaging a close
needs to know how much of the open pile needs investigation and how much needs a decision.

**The level bar is the signature element**, and it is the name made visible.

Two horizontal bars sharing a left origin. Upper bar = expected (payments − fees − refunds). Lower bar = received (the bank credit). A dashed **level line** marks where both must end. When they tie, both edges land on it and the pair reads as one solid block. When they don't, the lower bar falls short and the gap — the only coloured element on the screen — is the finding.

It appears at three scales, same element every time:
- **Period** — the close screen header
- **Batch** — one settlement, in the exceptions list
- **Record** — one payment, in the detail view

Clicking the gap filters the exceptions list to what caused it.

### 9.2 Exceptions

The working screen. This is what stays open during the demo video.

- One row per exception: code chip, amount delta, one-line reason, rung that gave up
- Filter by code, by amount, and by **breaks vs questions** (`is_break`)
- Sort by rupee impact descending by default — biggest money first, always
- Row count and total ₹ always visible in the header, split into breaks and questions
- Keyboard navigable: `j`/`k` to move, `Enter` to open, `r` to resolve

### 9.3 One exception, opened

The screen that proves the tool is trustworthy.

- Both sides of the mismatch, side by side, aligned on the field that differs
- The arithmetic, shown: `₹4,200.00 expected − ₹4,114.00 received = ₹86.00 short`
- The attempt trail: what R0 tried, what R1 tried, why R2 was skipped, what R3 proposed and why the validator rejected it
- Two actions: **Accept match** / **Keep open**, with a required one-line note
- Decisions are remembered so the same exception does not reappear next month

**E14 renders differently, and it is the best case in the product.** Instead of one mismatch, the
screen shows each candidate subset as its own level bar, all tying exactly to the same credit,
with the settlements inside each one listed. The copy states plainly that the system found more
than one valid answer and declined to choose. The reviewer picks one, or keeps it open.

A system that knows what it does not know is the most persuasive thing a tool touching money can
demonstrate. Build this screen with E14 in view, not as an afterthought.

---

## 10. Design direction

### Ground
This is a tool for one person doing careful work under time pressure at month end. It should feel like a well-made instrument, not a dashboard. Its material world is the settlement report and the bank narration string: machine-emitted, uppercase, truncated, monospaced.

**The visual grammar is the name.** Every element in the product is one idea at a different scale: **two sides that either line up or they don't.** Not cards, not charts, not tiles. Alignment and misalignment carry all the meaning.

**Deliberately not:** the cream-and-terracotta look, the dark-mode-with-acid-accent look, the broadsheet-hairline look. Also not a generic SaaS dashboard with cards and donut charts.

### The element set — all derived from level

| Element | What it is | Where |
|---|---|---|
| **Level bar** | Two bars, shared origin, gap = finding | Period, batch, record |
| **Level line** | Dashed vertical marking where both sides must end | Inside every level bar |
| **Offset row** | An exception renders as two short bars that don't align — no badge, no icon | Exceptions list |
| **Decimal spine** | Money columns align on the decimal down the full page | Everywhere |
| **Bucket meter** | Each exception code as a small level bar showing its share of ₹ open | Exceptions header |
| **Candidate stack** | Several level bars all tying to the same credit — the E14 view | Exception detail |
| **Tied state** | Fully reconciled = monochrome screen, every right edge flush | Close screen |

The ragged right edge of a scrolling exceptions list tells the user the state of their month before they read a single number. That is the design doing work.

### Palette — six values, colour used only for money states

```
--paper      #FBFBF9   background, faintly warm, not cream
--ink        #14161A   text and matched figures
--rule       #DEDEDA   hairlines, table borders
--muted      #6E7178   labels, metadata, secondary text
--open       #B86B0A   ochre — needs review, the only accent on the close screen
--risk       #A61E24   deep red — money confirmed lost or at risk
```

Restraint is the design. If everything tied, the screen is monochrome. Colour appearing means money needs attention. That correspondence must hold everywhere with no exceptions.

**E14 uses `--open`, never `--risk`.** No money is at risk in an ambiguity; a decision is
outstanding. Using the risk colour would tell the controller to panic about a question.

### Type — IBM Plex, full family

- **Display / headings:** IBM Plex Sans, weight 600, tight tracking (`-0.02em`)
- **Body / UI:** IBM Plex Sans, 400/500
- **All figures, ids, narrations, codes:** IBM Plex Mono

Chosen because it is the type of enterprise finance software, has real character in its `a` and `g`, and has genuine tabular figures. **Every numeral in the product uses `font-variant-numeric: tabular-nums`.** Money columns are right-aligned and must align on the decimal down the entire column. This is functional, not decorative — misaligned figures are unreadable in a reconciliation tool.

### Type scale
```
display  32px / 600 / -0.02em
h2       20px / 600 / -0.01em
body     15px / 400
label    12px / 500 / 0.06em / uppercase / --muted
figure   15px mono / tabular-nums
figure-l 28px mono / tabular-nums
```

### Layout
Dense over airy. This is a work tool; a controller scanning 42 exceptions wants rows visible, not whitespace. Row height 40px. Table-first. One accent per screen, maximum.

### Motion
Almost none. A 120ms fade on filter changes.

One exception, and it is the only orchestrated moment in the product: **on load, the received bar grows from zero and settles at its true length**, so the user watches it fall short of the level line. 400ms, ease-out, once per run. Nothing else animates. Respect `prefers-reduced-motion` — with it on, the bar renders at final length immediately.

### Quality floor, unannounced
Responsive to 768px minimum. Visible keyboard focus rings. Reduced motion respected. Colour never the sole carrier of meaning — every coloured state also has a text label.

---

## 11. Copy rules

- Name things by what the user recognises: "bank credit", not "ingested_txn_record"
- Buttons say what happens: **Run reconciliation**, not "Submit". The action keeps its name through the flow — "Run reconciliation" produces "Reconciliation complete"
- Errors state what happened and what to do, without apology: *"Row 412 in payments.csv has no amount. Fix the row or remove it, then upload again."*
- Empty states are invitations: *"No exceptions in this period. Every credit tied to the paisa."*
- E14 copy is factual, never apologetic: *"Two combinations tie exactly to this credit. Pick one, or keep it open."* Not *"Sorry, we couldn't determine…"* — refusing to guess is correct behaviour, and the copy should read like a decision rather than a failure.
- Never "insights", "powered by AI", "leverage", "seamless", "smart"
- Sentence case everywhere except the `label` type role

---

## 12. Metrics the tool must report

Printed to console after every run, written to `eval/results.json`, and shown in the UI.

```
auto-match rate            %
precision of auto-matches  %      ← must be ~100%
recall                     %
payment coverage           %      ← the honest headline; see below
ambiguity rate             %      ← E14 as a share of bundled credits
exception rate by code     table, split by is_break
₹ reconciled / ₹ open
₹ discrepancy found        ← headline
rung attribution           R0/R1/R2/R3 split
absorbed tolerance drift   ₹
cost per 1,000 records     ₹
p50 / p95 latency          s      ← only once there is a distribution; see below
```

**Coverage is reported as three buckets, with the strict number leading.** Reconciled to bank
is the sign-off figure and nothing softens it. In transit — settled after the statement closes —
is a normal period-end state, not a gap, and reporting it inside the same number as money that
never arrived conflates a clock with a break. Still open is itemised by code rather than
totalled, because E02, E04 and E14 are three different problems with three different actions.
Measured: in transit is 31% of the train gap and 40% of held-out *(train+heldout, 6b,
2026-09-01)* — a large minority, not the bulk, so the split clarifies the number rather than
rescuing it.

**Payment coverage is the number to quote, not credit match rate.** Credit-level match rate
flatters the result: an unmatched bundled credit carries several settlements' worth of payments,
so a small count of unmatched credits can hold a large share of the money. The merchant's money
is in the payments. `EVAL.md` reports both and leads with coverage.

**Ambiguity is reported as a count with its denominator, and reported even when it is zero.**
Zero is a finding about the candidate filter, not a blank — and it is only meaningful next to
the unfiltered comparison. `EVAL.md` states both, at the window §5 derives: with the window
on, 1 of 8 train bundles and 1 of 6 held-out are ambiguous; with no date filter, 2 of 8 train
and 1 of 6 held-out are *(train+heldout, 6b, 2026-09-01)*. The filter is doing the work, and the number is what proves it. **This paragraph must not
restate the window's value** — that is §5's job, and stating it twice is how the ±5 → ±6
correction came to be applied in one place and missed here.

**The identity gap is reported attributed, not as a lump.** PRD §8's identity does not close
on injured data, and `EVAL.md` states what the gap is made of rather than quoting a residue:
it equals the summed `delta_paise` of the bank-side break codes — E01, E02, E03, E04 — with
the sign reversed, to the paisa. Those four move `credit_paise` with no matching movement on
the ledger side; every other code either moves both sides together (E05, E10, E11) or moves no
money (E06–E09, E12, E13). Measured exact on both seeds *(train+heldout, 6b, 2026-09-01)*:
₹4,25,965.19 train and ₹1,28,136.82 held-out, fully attributed, zero unexplained. A residue
reported without attribution is a number nobody can act on, and the exception classifier's
completeness cannot be tested against an identity that does not close.

**Latency percentiles are reported only once there is a distribution to describe.** Two identical
percentiles of a one-sample population is a metric shaped like a measurement. Until R3 gives the
run a real per-unit distribution, the field is omitted rather than filled with a placeholder.

### Required before/after measurements
Two numbers that must be captured during the build, because they are the entire AI-judgment argument:

1. Payment coverage **before and after** R2 (the deterministic combination solver)
2. Payment coverage **before and after** R3 (the LLM rung)

If R3's delta is small, report it honestly and say so. "The LLM cleared 3.7% of records and cost ₹18" is a stronger sentence than any inflated claim.

---

## 13. Deliverables

```
README.md          the problem, the person, the ₹ cost, quickstart in 3 commands
ARCHITECTURE.md    the ladder, the safety rules, LLM-has-no-write-path,
                   trade-offs considered and rejected
DECISIONS.md       6+ dated entries: what broke, what changed, number before → after
EVAL.md            full metrics table + the honest exception list
src/generate/      generator + ground truth (isolated from the engine)
src/ingest/        parsers, normalisation, validation
src/match/         r0, r1, r2, r3, validator
src/audit/         fee variance auditor
src/report/        close summary, metrics
web/               three screens
eval/              harness, held-out set, results.json
tests/             unit + property-based invariant tests
```

Plus: a deployed URL, and a 5-minute video.

---

## 14. Acceptance criteria

The build is done when all of these are true:

1. `make demo` runs end to end on 5,000 records and prints the metrics block
2. Auto-match precision is ≥ 99.5% measured against held-out ground truth
3. Every ingested record ends in exactly one state: matched, exception, or unprocessed — with counts and ₹ totals both reconciling to the ingested totals. (Malformed rows are not a fourth state: nothing loads until they are fixed, per §4.)
4. Re-running identical inputs produces identical **accepted matches**, and creates zero new
   ones. Stated this way because the literal version cannot hold for a model call and pretending
   otherwise would be the criterion lying. What is true and stronger: the validator is
   deterministic, and the proposal layer is reproducible because every model response is cached
   on a hash of its exact prompt and the cache is committed. So reruns are byte-identical, and
   **a stranger can clone the repo and reproduce every number in it with no API key at all** —
   which matters more than the determinism does. The cache is regenerated only deliberately.
5. The engine never reads the ground-truth file (assert this in a test)
6. No float appears anywhere in a money path (assert this in a test)
7. The LLM cannot write a match without deterministic validation (assert this in a test)
8. **R2 never returns a match where more than one subset ties exactly** — assert this in a test, using a hand-constructed two-solution case as well as generated decoys
9. The exceptions screen is fully keyboard navigable, and separates breaks from questions
10. `results.json` contains before/after payment coverage for R2 and R3
11. A stranger can clone the repo and see the close summary in under 5 minutes

---

## 15. Build order

Note that the eval harness lands before the LLM. That ordering is deliberate — it is how you prove the LLM's marginal contribution rather than assuming it.

1. Money primitives — `Paise`, rounding, the no-float guard
2. Synthetic generator + ground truth
3. Ingest, normalise, validate
4. R0 + R1 matching
5. **Eval harness → first number on the board**  ← held-out
6. R2 combination solver → measure the delta  ← held-out
   - **6a.** Regenerate with decoy bundles; baseline re-established
   - **6b.** The solver itself, with the uniqueness guard
7. Exception taxonomy + classifier
8. Fee variance auditor
9. R3 LLM rung + validator → measure the delta  ← held-out
10. Close summary screen
11. Exceptions screen
12. Exception detail screen + review decisions
13. Docs, deploy, video  ← held-out, final `EVAL.md`

Step 6 is split because regenerating the data invalidates the step 5 baseline. 6a must settle and
its tests pass before the solver is built on top of it — otherwise a coverage delta cannot be
attributed to the solver rather than to the new data.