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
| **R2** | Combination: which subset of payments sums to this credit | No | ~10% |
| **R3** | LLM: narration parsing, entity resolution, explanation | Yes | ~5% |

**These four percentages are a generator target, not a measurement.** The rung split is set by
the structure of the data — how often a credit bundles several settlements, and how often the
UTR is recoverable from the narration — so it is something the generator decides and `EVAL.md`
reports. `EVAL.md` prints what actually came out, next to this table, and explains any gap.

### R2 is worth building properly
"Which subset of these 400 payments sums to ₹4,32,187.55 within ₹1?" is a subset-sum problem. Solve it algorithmically (meet-in-the-middle, or DP with a bounded candidate window after filtering by date and amount range). Do **not** hand this to the LLM — it will be slower, non-deterministic, and worse. Building this deterministically and saying so is a deliberate signal.

### The safety rule
> **The LLM proposes. Deterministic code disposes.**

R3 emits a *candidate* match with a confidence and a rationale. A deterministic validator re-checks the arithmetic. If the amounts do not tie to the paisa, the candidate is rejected regardless of stated confidence. **The LLM never writes a match directly.** State this verbatim in the architecture notes.

### Tolerance

**Tolerance is 100 paise (₹1.00) absolute, per match, whole-match — not per record inside it.** It is not a percentage, and it does not scale with the amount: ₹1 of rounding drift on a ₹4 lakh credit is the same ₹1 as on a ₹400 one.

Tolerance exists for one reason: rounding drift. It is never spent to absorb a fee difference, a missing refund, or a partial settlement. Those are findings.

- Match ties to the paisa → matched, clean.
- Match ties within 100 paise → matched, flagged **E03**, delta recorded.
- Outside 100 paise → not a match. **E04**.

**R2 spends tolerance only against a unique solution.** If more than one distinct subset lands inside the window, the solver returns no match and raises an exception. A ₹1 window over a large candidate pool will manufacture plausible-looking sums, and a false match hides a real break — so the solver counts solutions, stops at two, and gives up. This uniqueness check is the precision guard for the whole rung.

Any match that consumes tolerance is flagged, and total absorbed drift is reported at the end of every run. Silently absorbing ₹0.50 four thousand times is ₹2,000 invented from nothing. If absorbed drift for a run exceeds ₹100, the run says so at the top of the summary rather than in a footnote.

### Precision over recall
In reconciliation, a false match is worse than no match, because it **hides a real break** and someone signs off on wrong books. Target near-100% precision on auto-matches; trade recall to get it. Say this explicitly in the UI and the docs.

---

## 6. Exception taxonomy

Fixed codes so runs are comparable month to month. **Thirteen codes, all of which the generator
produces and the eval scores.** There is no E14 — it was a currency/FX code, and a rupee-only D2C
merchant has no FX line. Thirteen codes that all fire beats fourteen with a dead one, and a code
with no test data is a code that is wrong in production and never fails a test.

| Code | Meaning |
|---|---|
| E01 | Bank credit with no matching settlement (unidentified receipt) |
| E02 | Settlement with no bank credit (in transit or missing) |
| E03 | Amount mismatch within tolerance — matched, flagged |
| E04 | Amount mismatch outside tolerance — break |
| E05 | Fee variance vs contracted rate |
| E06 | Payment with no order (orphan) |
| E07 | Order with no payment |
| E08 | Refund not linked to an original payment |
| E09 | Chargeback debit absent from orders |
| E10 | Duplicate payment against the same order |
| E11 | Partial refund drift |
| E12 | Period cutoff (paid in month M, settled in M+1) |
| E13 | Unparseable narration |

Every exception row carries: code, both record ids, the rupee delta, the rung that gave up, and a one-sentence plain-English reason.

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

Compare to actual. Every mismatch is a rupee-denominated finding. Aggregate into the headline: **"₹8,412 in fee overcharges across 214 payments this period."**

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
  "expected_fees": {                 // the answer key for the audit
    "pay_...": {"fee_paise": 1200, "gst_paise": 216}
  },
  "totals": {"gross_paise": 0, "fee_paise": 0, "gst_paise": 0,
             "refund_paise": 0, "adjustment_paise": 0,
             "credit_paise": 0, "in_transit_paise": 0}
}
```

A match is scored as a whole: the engine's `payment_ids` set must equal the ground-truth set exactly. Four of five payments right is one false positive, not four true positives — this is the unit for both precision and recall, and it is the reason the numbers in §12 mean anything.

`totals` exists so the eval can assert the conservation identity, which is the invariant everything else rests on. Note the sign on adjustments — they are **signed** and therefore added; they run both ways, and subtracting them would silently double every credit adjustment:

```
Σ gross − Σ fee − Σ gst − Σ refund + Σ adjustment − in_transit  ==  Σ credit + ₹open
```

### Scale
5,000 payments across ~60 settlement batches over 3 months. The brief asks for 50+ records; delivering 100× that is the cheapest way to clear the throughput bar.

### Structural knobs — these set the rung split

Break rates do not decide how hard the data is to match. Two structural facts do, and both are
named parameters recorded in `ground_truth.json`:

```
credit bundles > 1 settlement    12%      (2–5 settlements per bundled credit)
UTR in narration                 78% verbatim / 12% truncated / 6% garbled / 4% absent
```

Bundling is the only reason R2 exists. UTR recoverability is the whole of the R0/R1/R3
boundary. Stating them as parameters is what lets §12's rung attribution be read as a
consequence of a declared distribution rather than presented as a discovery.

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
│  42 items open · ₹2,84,000                           │
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
- Filter by code, by amount, by "money at risk vs cosmetic"
- Sort by rupee impact descending by default — biggest money first, always
- Row count and total ₹ always visible in the header
- Keyboard navigable: `j`/`k` to move, `Enter` to open, `r` to resolve

### 9.3 One exception, opened

The screen that proves the tool is trustworthy.

- Both sides of the mismatch, side by side, aligned on the field that differs
- The arithmetic, shown: `₹4,200.00 expected − ₹4,114.00 received = ₹86.00 short`
- The attempt trail: what R0 tried, what R1 tried, why R2 was skipped, what R3 proposed and why the validator rejected it
- Two actions: **Accept match** / **Keep open**, with a required one-line note
- Decisions are remembered so the same exception does not reappear next month

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
- Never "insights", "powered by AI", "leverage", "seamless", "smart"
- Sentence case everywhere except the `label` type role

---

## 12. Metrics the tool must report

Printed to console after every run, written to `eval/results.json`, and shown in the UI.

```
auto-match rate            %
precision of auto-matches  %      ← must be ~100%
recall                     %
exception rate by code     table
₹ reconciled / ₹ open
₹ discrepancy found        ← headline
rung attribution           R0/R1/R2/R3 split
absorbed tolerance drift   ₹
cost per 1,000 records     ₹
p50 / p95 latency          s
```

### Required before/after measurements
Two numbers that must be captured during the build, because they are the entire AI-judgment argument:

1. Match rate **before and after** R2 (the deterministic combination solver)
2. Match rate **before and after** R3 (the LLM rung)

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
4. Re-running identical inputs produces identical output and creates zero new matches
5. The engine never reads the ground-truth file (assert this in a test)
6. No float appears anywhere in a money path (assert this in a test)
7. The LLM cannot write a match without deterministic validation (assert this in a test)
8. The exceptions screen is fully keyboard navigable
9. `results.json` contains before/after numbers for R2 and R3
10. A stranger can clone the repo and see the close summary in under 5 minutes

---

## 15. Build order

Note that the eval harness lands before the LLM. That ordering is deliberate — it is how you prove the LLM's marginal contribution rather than assuming it.

1. Money primitives — `Paise`, rounding, the no-float guard
2. Synthetic generator + ground truth
3. Ingest, normalise, validate
4. R0 + R1 matching
5. **Eval harness → first number on the board**  ← held-out
6. R2 combination solver → measure the delta  ← held-out
7. Exception taxonomy + classifier
8. Fee variance auditor
9. R3 LLM rung + validator → measure the delta  ← held-out
10. Close summary screen
11. Exceptions screen
12. Exception detail screen + review decisions
13. Docs, deploy, video  ← held-out, final `EVAL.md`
