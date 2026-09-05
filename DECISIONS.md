# Decisions

## State — as of 2026-08-29

Read `PRD.md` and `CLAUDE.md` first. This section is where the build actually is.

### Steps complete (PRD §15, renumbered — money primitives is now step 1)

| Step | What it produced |
|---|---|
| 1 ✅ | `src/money.py` — `Paise` (a `NewType` over `int`), `mul_bps` (integer basis points, rounds half away from zero), `format_rupees` (Indian digit grouping). The no-float guard lives in `tests/test_money.py::test_no_floats_in_src`: it parses every module under `src/` and fails on float literals, `/`, `round()`, or the name `float` anywhere. |
| 2 ✅ | `src/generate/` — `world.py` (clean world), `breaks.py` (injection), `__main__.py` (CLI). Writes CSVs to `data/<name>/` and the answer key to `eval/ground_truth/<name>.json`. |
| 3 ✅ | `src/ingest/` — `load.py` (schema table, date/money normalisation, loud validation), `__main__.py` (CLI). |
| 4 ✅ | `src/match/ladder.py` — R0 (verbatim UTR from narration + amount ties) and R1 (amount + ±2-day window + partial reference), one-claim-per-settlement, disputed settlements locked out of every rung. `src/match/__main__.py` prints rung counts. |
| 5 ✅ | `eval/harness.py` — whole-match scoring against the answer key, conservation and partition checks, metrics to `eval/results.json` keyed by set and rung set. |
| 6a ✅ | `world._decoys` — decoy bundles built from settlements that survive the ladder, so E14 has data and the engine refuses it. Both seeds regenerated. |
| 6b ✅ | `src/match/ladder.py` — R2: bounded pool, exact ties only, uniqueness guard, E14 carrying every candidate. `run(ledger, through=...)` reproduces the before/after. |
| 7 ⬜ | **Next: exception taxonomy + classifier.** |

95 tests passing. No known failures, nothing skipped except the two dataset tests when
`data/` is absent.

### Commands

```bash
uv run pytest -q                                  # 82 tests
PYTHONPATH=src uv run python -m generate train    # writes data/train + eval/ground_truth/train.json
PYTHONPATH=src uv run python -m generate heldout  # writes data/heldout + eval/ground_truth/heldout.json
PYTHONPATH=src uv run python -m ingest data/train # prints row counts, or every bad row and exits 1
PYTHONPATH=src uv run python -m match data/train  # prints the R0/R1 rung split and absorbed drift
PYTHONPATH=src uv run python eval/harness.py heldout   # scores against the answer key, writes eval/results.json
```

`PYTHONPATH=src` is required — `pyproject.toml` sets `pythonpath = ["src"]` for pytest only.
There is no `make demo` yet; that is step 13.

### Current numbers

```
train    seed 20260101   5,042 payments  64 settlements  46 bank rows   8 bundled credits  1 E14
                         192 breaks: E01 2  E02 2  E03 5  E04 1  E05 71  E06 15  E07 16
                                     E08 3  E09 1  E10 38  E11 33  E12 2  E13 3
heldout  seed 20260331   5,038 payments  64 settlements  46 bank rows   6 bundled credits  1 E14
                         191 breaks
```

`eval/results.json` is keyed `<set> → <rung set>`, so the R0+R1 baseline survives alongside
the R2 number and acceptance criterion 10's before/after needs no special-cased field.
`run(ledger, through="R1")` regenerates the baseline from the same code.

| | held-out R0+R1 | held-out R0+R1+R2 | train R0+R1 | train R0+R1+R2 |
|---|---|---|---|---|
| **payment coverage** | 58.24% | **88.73%** | 52.24% | **86.97%** |
| auto-match rate | 82.61% | 93.48% | 76.09% | 91.30% |
| precision | 100.00% | **100.00%** | 100.00% | **100.00%** |
| recall | 88.37% | **100.00%** | 81.40% | **97.67%** |
| E14 refused | — | 1 of 6 bundled | — | 1 of 8 bundled |
| rung split | 32 / 6 | 32 / 6 / 5 | 23 / 12 | 23 / 12 / 7 |

**Quote payment coverage, not the auto-match rate.** 93.48% of held-out credits are matched
but 88.73% of payments sit inside a matched credit; the merchant's money is in the payments.
R2's contribution is far larger on the payment number than the credit number, and that is
the honest frame for it.

**R2's delta is +30.49 points held-out, +34.73 train.** Both measured on the same data before
and after, not across a regeneration.

### Decisions made in conversation that ARE now in PRD.md

All of these were patched in, so `PRD.md` is current: the five-file input set with
`refunds.csv`; the ground-truth schema and match-scoring unit; tolerance at 100 paise with
R2's uniqueness rule; per-method rates in basis points; `customer_name`/`pincode`;
E14 deleted (thirteen codes); the structural knobs; the five added codes and the E07
qualifier; `SEED_TRAIN`/`SEED_HELDOUT` and the held-out discipline; §15 renumbered; the
one-pass-then-load-nothing ingest rule.

### Decisions NOT in PRD.md — they live only here

1. **Break rates name their own population and carry a floor of one row.** PRD §8's flat
   percentages assume a 5,000-row denominator; narration lives on 46 bank rows, where 1.0%
   is zero rows and the code never fires. See the step 2 entry. The real rates are the
   constants at the top of `src/generate/breaks.py`.
2. **Every §12 metric gets an integer unit** — match rates in basis points, latency in
   milliseconds, cost in paise. No float, no exemption, no `src/report/` allowed path. See
   the "No exemption for ratios" entry.
3. **`Path.joinpath()` instead of `/` everywhere under `src/`,** because the no-float scan
   reads `/` as division and is right to. Not an exemption — the code moved.
4. **The generator keeps its own copy of the rate card.** `src/audit/` must define its own
   when it is built. An auditor importing `world.FEE_BPS` tests that a constant equals
   itself.
5. **Rows are dicts, not dataclasses,** through generator and ingest. `Ledger` is the only
   container. Revisit if the matcher makes attribute access worth it.
6. **`delta_paise` means effect on money received this period.** In-transit settlements
   move no bank money, so breaks landing on them record 0. Linkage breaks (E06–E09, E13)
   record 0 by nature.

### Half-done or knowingly deferred

- **`make demo` does not exist** (step 13). Neither does `README.md` quickstart, `EVAL.md`,
  or `ARCHITECTURE.md`. `README.md` in the repo is the original stub.
- **Resolved: `data/` and `eval/ground_truth/` are tracked in git** (~3MB). Regenerable from
  seed, but tracked means a clone reproduces the numbers without running the generator.
- **`.gitignore` carries `*.md` with `!README.md`, so `PRD.md`, `CLAUDE.md` and `PROMPTS.md`
  are on disk but NOT in the repo** (commit `a3857bf`). They still load for a local session.
  But acceptance criterion 10 is "a stranger can clone the repo and see the close summary" —
  a stranger currently clones without the spec. Decide before step 13 whether `PRD.md` ships.
- **Typer is not installed or used.** Both CLIs are `python -m` with `sys.argv`. Add Typer
  when there is a third command.
- **Persistence for review decisions is unchosen** (PRD §9.3, step 12). It must survive a
  restart, write atomically, and feed acceptance criterion 4. SQLite, one file. Not built.
- **Two spec inconsistencies flagged and deliberately not fixed:** PRD §1 describes
  150–400 orders/day while §8 asks for 5,000 payments over 3 months (≈55/day) — the README
  must not claim both. And UPI is 0 bps by contract at 62% of the method mix, so three in
  five payments have no fee to audit; the §7 headline will be smaller than "2% of
  everything" implies.
- **Acceptance criterion 4 vs the LLM** is unresolved. "Identical inputs produce identical
  output" cannot hold literally for R3, and remembered review decisions change the next run
  by design. Needs restating before step 9.
- **The `unprocessed` state is defined but nothing produces it yet.**
- **`in_transit_paise` is borrowed from the answer key by `eval/harness.py`.** It is the one
  total in PRD §8's identity that is not derivable from the CSVs, because deriving it needs a
  period boundary the engine does not have until step 7. The harness is allowed to read the
  answer key — that is its job — but it means the `unexplained` figure is not yet a number the
  engine could produce on a real merchant's files. Retire the borrow at step 7.
- **The identity residue (₹1,06,154.57 held-out) is reported, not asserted to zero.** It is
  the injected damage: `world.assert_identity` runs on the *clean* world before
  `breaks.injure`, and breaks are money that no longer ties by definition. Attributing it
  code by code is step 7's completeness test. The half that IS asserted every run: the six
  CSV-derivable totals reproduce the answer key to the paisa.
- **p50/p95 latency is deliberately absent from `results.json`.** The whole run is 0–1ms with
  no per-unit distribution; two identical percentiles of a one-sample population is a metric
  shaped like a measurement. It lands at step 9 with R3's per-call latency. `run_ms` is the
  one field that is not reproducible, and the reproducibility test excludes it.
- **Ingest matches CSV headers by exact string, so a whitespace-padded header rejects the
  whole file.** An editor column-aligned `data/heldout/bank_statement.csv` on 2026-08-29 and
  ingest refused all 46 rows with `bank_statement.csv has no txn_date or narration or ...`.
  Every *value* is stripped; the *fieldnames* are not. Restored from git, held-out reproduced
  80.43% exactly. The loud failure worked as designed, but a padded header is readable data
  and arguably should not be a rejection — one line in `_read`, not yet taken.

---

## 2026-08-29 — Step 1: money primitives

**Built.** `src/money.py`: `Paise` (a `NewType` over `int`, so it is an int at runtime and
carries no wrapper-class overhead), `mul_bps`, `format_rupees`. `tests/test_money.py`.
20 tests passing.

**What broke: the fee formula in the PRD was wrong for negative amounts.**
PRD §7 specified `expected_fee = (amount_paise * fee_bps + 5000) // 10000`. Python's `//`
floors rather than truncating, so for a refund of -100 paise at 200 bps it returns **0**
where the correct answer is **-2**. Every reversal in the book would have under-refunded by
up to one paisa, and the error is invisible — it produces a plausible number, not a crash.

Changed: `mul_bps` takes `abs()`, rounds half away from zero, then reapplies the sign, so a
fee and its reversal are always equal and opposite. That invariant is now a Hypothesis
property test. PRD §7 updated to match.

**Rounding rule chosen: half away from zero,** not banker's rounding. A fee of 0.5 paise
bills as 1 and refunds as 1. Banker's rounding would break the equal-and-opposite invariant
above, and no Indian payment aggregator uses it for fee computation.

**The no-float test is static, not runtime.** It parses every module under `src/` and fails
on float literals, true division, and calls to `float()`/`round()`. Runtime `isinstance`
checks would never catch the likeliest form of this bug — a display helper doing
`paise / 100`, which is only reached at render. Verified the guard actually bites by
planting `return p / 100` in a throwaway module: the test failed with the file and line.
Scoped to all of `src/`, permanently, with no exemptions and no escape comment.

**Indian digit grouping is hand-rolled.** `f"{n:,}"` groups in thousands and renders
`432,187` where a merchant reads `4,32,187`. Integer string slicing, no locale dependency.

---

## 2026-08-29 — Step 1 audit: four fixes before step 2

Swept what step 1 produced, spec included. 20 tests still passing.

**1. The no-float test had a hole: `float` as an annotation.** It only flagged `float(...)`
as a *call*, so `def f(x: float) -> float` passed clean — and a signature is exactly where a
float enters a codebase and then propagates everywhere by inference. Now flags the name
`float` wherever it appears (call, annotation, `isinstance` check). Verified by planting
`def bad(x: float) -> float` under `src/`: caught, twice, with line numbers.

**2. Wrong sign on adjustments in the conservation identity (PRD §8).** I had written
`− Σ adjustment`. Adjustments run both directions and are signed, so they are **added**:

```
Σ gross − Σ fee − Σ gst − Σ refund + Σ adjustment − in_transit  ==  Σ credit + ₹open
```

Subtracting a signed value double-counts every credit adjustment, in the one equation the
whole eval asserts against. Nothing was built on it yet, which is the cheapest moment to
find it.

**3. Refund sign convention was unstated (PRD §4).** `refunds.csv.amount_paise` is now
declared a positive magnitude, with direction carried by `type`; negatives are malformed
rows. Signed amounts would have been equally defensible — the bug is not the choice, it is
two modules quietly making opposite choices, and a refund landing as an addition.

**4. The rate card had no closed method set (PRD §7).** `fee_bps` is a dict lookup on
`payment.method`. An unlisted method either crashes the audit mid-run or, if someone
"fixes" it with `.get(method, 0)`, silently bills 0 bps and reports zero variance across an
entire payment method. Method set is now closed at `upi | card | netbanking | wallet`, with
ingest rejecting anything else by row number.

Three of the four are spec bugs, not code bugs. Fixing them at the doc costs a line; fixing
them after the generator and the auditor have both encoded the wrong convention costs a day.

---

## 2026-08-29 — No exemption for ratios either

Retracting a plan from the step 1 entry above. I had written that the match-rate percentage
at step 4 would "collide with" the no-float scan and that the fix would be an allowed path
for `src/report/`. That was wrong, and pre-authorising an exemption is how the rule dies.

The reason integers work for money is that paise is the smallest unit that exists, so there
is no fraction left to lose. A float stores ₹1,234.56 as an approximation, because most
decimal fractions have no exact binary form — 0.1 in binary repeats the way 1/3 does in
decimal, and gets truncated.

That argument is not specific to money. It applies to every ratio in §12, so all of them get
an integer unit:

| Metric | Unit stored | Rendered |
|---|---|---|
| match rate, precision, recall | basis points, int | `3514 * 10000 // 5000` -> `7028` -> `70.28%` |
| p50 / p95 latency | milliseconds, int | `41300` -> `41.3s` |
| model cost | paise, int | reuses `format_rupees` |
| absorbed drift | paise, int | reuses `format_rupees` |

No floats in `src/`. No allowed paths, no escape comment, and no metric that needs one.

---

## 2026-08-29 — Step 2: synthetic generator + ground truth

**Built.** `src/generate/world.py` (clean world), `src/generate/breaks.py` (injection),
`src/generate/__main__.py` (CLI). `tests/test_generate.py`. 30 tests passing.

```
train   seed 20260101   5,040 payments  64 settlements  46 bank rows   8 bundled credits
                        200 breaks: E01 2  E02 2  E03 5  E04 1  E05 75  E06 15  E07 16
                                    E08 3  E09 1  E10 40  E11 35  E12 2  E13 3
heldout seed 20260331   5,040 payments  64 settlements  46 bank rows   6 bundled credits
                        204 breaks
```

All thirteen codes fire in both sets. CSVs to `data/<name>/`, answer key to
`eval/ground_truth/<name>.json` — different trees, so the engine has no reason to know
`eval/` exists.

**What broke: the answer key claimed 60,855 paise that never reached a bank.**
Fee-variance, duplicate-payment and partial-refund injections all adjust a settlement's net
and the bank credit carrying it. For settlements that settle after the period ends there
*is* no bank credit — the money is in transit — so the settlement moved and the bank did
not, while the break still recorded a non-zero `delta_paise`. Caught by the invariant
`credit_before + sum(delta) == credit_after`, asserted on every run.

Fixed: `_shift` now returns what actually reached the bank, and the break records that. A
fee overcharge on an in-transit batch is still a real finding, but its effect on money
received **this period** is zero, and the answer key now says zero. `in_transit_paise` is
recomputed after injection, since injection moves the very nets it is summed from.
Before -> after: 60,855 paise unexplained -> 0.

**The no-float scan's first collision was pathlib, not arithmetic.** `ROOT / "data" / name`
parses as `ast.Div` and the scan flagged it, correctly — it cannot tell path division from
true division. Fixed with `Path.joinpath()` at four sites. Second time the rule has been
pressed, second time the code moved instead: no exemption, no escape comment. `joinpath` is
not worse than `/`.

**PRD §8's flat percentages do not survive contact with a 46-row bank statement.**
"unparseable narration 1.0%" is 0.46 rows — the code never fires and the eval can never
score it. The percentages implicitly assumed every rate applies to the 5,000-row payments
file, but narration lives on bank rows, missing settlements on settlements, and unlinked
chargebacks on the ~20 chargebacks. Each rate now names its own population and carries a
floor of one row. The denominator was the whole problem, and it was invisible while the
rates were written as bare percentages.

**E12 is emergent and small: 2 settlements, not §8's 3%.** Period cutoff is not injected —
it is what happens when T+2 settlement crosses the period end, and the generator labels it
at construction. Two batches is what the data produced. Reporting 3% would have meant
injecting fake cutoffs to hit a number written before the data existed.

**Bundled credits: 8 of 46 (17%) against a 12% knob.** The knob is applied per credit and
there are only 46 draws, so this sits inside noise. Recorded because the R2 delta is
entirely downstream of it — if bundling drifts, the R2 number moves for reasons that have
nothing to do with R2.

**Two things flagged rather than fixed:**

- PRD §1 describes a merchant doing 150-400 orders/day; §8 asks for 5,000 payments over 3
  months, which is 55/day. The two describe different merchants. §8 wins for now because
  throughput is the graded bar, but the README must not claim both.
- UPI is 0 bps by contract and is 62% of the method mix, so roughly three in five payments
  have no fee to audit. That is accurate to Indian zero-MDR reality rather than a modelling
  shortcut, but it means the §7 headline will be smaller than a naive 2%-of-everything
  estimate suggests.

---

## 2026-08-29 — Step 3: ingest, normalise, validate

**Built.** `src/ingest/load.py` (schema table + reader), `src/ingest/__main__.py` (CLI).
`tests/test_ingest.py`. 52 tests passing.

```
data/train    5416 orders  5040 payments  176 refunds  64 settlements  46 bank rows
data/heldout  5416 orders  5040 payments  185 refunds  64 settlements  46 bank rows
```

**Settled the contradiction I flagged in the first session and had left open.** PRD §4 said
"reject malformed rows loudly"; acceptance criterion 3 allowed an `unprocessed` state, which
reads as keeping them. Those are different products. Decided: **report every bad row in one
pass, then load nothing.**

- First-error-and-stop makes fixing a file an N-round-trip.
- Load-the-good-ones produces a close that looks clean and is wrong by however many rows
  were dropped — the exact failure the tool exists to prevent.

PRD §4 and §14.3 updated so the two no longer disagree. `unprocessed` now means a record
that loaded fine and that no rung claimed, which is a real state worth counting.

**The line ingest holds: it rejects rows it cannot read, never rows that look wrong.** A
payment with a blank `order_id` is E06. A refund with no `payment_id` is E08. A payment in
no settlement batch is E02. All three must load, or the tool finds nothing and reports a
clean month. Only unreadable data is refused: empty amount, decimal point in a paise
column, unknown date format, unknown payment method, repeated id. There is a test for each,
and a test that the findings survive.

Real output on a deliberately corrupted copy of `data/train`:

```
4 rows could not be read. Nothing was loaded.

  Row 8 in payments.csv: amount_paise has a decimal point -- money is whole paise, not rupees. Fix the row or remove it, then run again.
  Row 21 in payments.csv: amount_paise is empty. Fix the row or remove it, then run again.
  Row 413 in payments.csv: method is not one of upi, card, netbanking, wallet. Fix the row or remove it, then run again.
  Row 4 in bank_statement.csv: txn_date is not a date I recognise (expected DD/MM/YYYY, YYYY-MM-DD, DD-Mon-YY or YYYY-MM-DD HH:MM:SS). Fix the row or remove it, then run again.
```

Row numbers are file line numbers — the number a person sees in their spreadsheet, not a
zero-based record index.

**What broke: a test helper, not the module.** The corrupt-a-cell helper rebuilt the file
set from the pristine copy on every call, so two chained edits silently threw the first one
away and two tests asserted against data they had not actually produced. The helper now
takes the set it is editing. Worth writing down because it is the failure mode that makes a
test suite lie: both tests were green in spirit and testing the wrong input.

**Deliberately not built:** referential integrity checks. Whether a `settlement_id` points
at a real settlement is the matcher's question and the answer is an exception code, not an
ingest error.

---

## 2026-08-29 — Step 4: R0 + R1 matching

**Built.** `src/match/ladder.py` (both rungs, one module — `r2`/`r3` append to it),
`src/match/__main__.py` (rung counts). `tests/test_match.py`. 65 tests passing.

```
data/train   46 bank credits   64 settlements
  R0   24 credits   52.17%
  R1   11 credits   23.91%
  11 credits unmatched, 29 settlements unmatched
  5 matches consumed tolerance, drift absorbed ₹1.33
```

Scored against `eval/ground_truth/train.json` in a scratch script: **35 correct of 35
claimed, recall 35 of 44.** Precision is the number that matters and it is 100% on train.
`heldout` has not been opened — that is step 5.

The 9 misses are 8 bundled credits, which fail R0's amount test by construction and are R2's
entire reason to exist, plus one credit whose narration lost its UTR and whose amount and
date fit nothing inside a rupee. The two E01 unidentified receipts are correctly claimed by
nobody: 46 credits, 44 real matches.

**PRD §5's rung targets are already off, and it is the data, not the ladder.** §5 wants R0 at
~70% and R1 at ~15%; measured is 52.17% / 23.91%. The generator's UTR knob is 78% verbatim,
so ~36 of 46 credits carry a clean UTR — but 8 of those are bundles whose amount cannot tie
to a single settlement, so they fall through R0 by design. R0's ceiling on this data is the
verbatim-UTR share **minus** the bundled share, not the verbatim share. R1 picks up most of
what R0 drops. Nothing to fix; `EVAL.md` reports what came out, as §5 says it must.

**What broke: R1 quietly undid a refusal R0 had made.** When two bank credits both name the
same settlement, R0 correctly refuses both — first-credit-wins by file order is exactly the
false match that hides a real break. But R0 only declined to *claim* the settlement, so it
stayed open, and R1 then matched it to whichever of the two credits it reached first. The
guard was in the wrong rung.

Fixed: contention is a fact about the settlement, not about R0. The index now carries a
`disputed` set alongside `claimed`, and `open_settlements()` excludes both, so a settlement
two credits both name is out of every rung including the two not yet written. It still
reports as unmatched, because it is. Caught by
`test_two_credits_naming_one_settlement_give_no_match`, which failed on the first run.

**The anti-circularity test did not exist.** CLAUDE.md hard rule 3 and PRD §8 both say the
engine never reads the ground-truth file and that this is asserted in a test. Nothing
asserted it — there was no engine to assert it about until now. Added
`test_the_engine_never_reads_the_ground_truth_file`: static, like the no-float scan, walking
the AST of every module under `src/` except `src/generate/` and failing on the string
`ground_truth` or a bare `eval` path. A runtime check would only cover the paths a test
happened to walk.

**Narration parsing pulls candidates rather than parsing.** Any alphanumeric run of five or
more that is over half digits, then exact-lookup against the UTR index. Verbatim, truncated
and garbled UTRs all survive that filter; `RAZORPAY` and `XXXXX` do not, and a false
candidate token simply misses the index. Writing a regex per narration template would fit
the five templates the generator emits and break on the sixth a real bank sends.

**R1's window is ±2 days and one rupee, and the partial reference narrows rather than
decides.** Candidates must first fit amount *and* date; a truncated-prefix or one-character-
substitution match against the UTR then narrows that set. If the partial reference finds
nothing, the amount-and-date set stands. Either way, two survivors means no match — the same
uniqueness guard R2 needs for subset sums, written once here.

**Deliberately not built:** exception codes. R0/R1 return unmatched credits and unmatched
settlements as lists; whether an unmatched settlement is E02, E12 or in transit is step 7's
question, and the ladder should not be guessing at a period boundary it cannot see.

---

## 2026-08-29 — Step 5: eval harness, first number on the board

**Built.** `eval/harness.py` (scorer, conservation check, partition check, `results.json`
writer). `tests/test_eval.py`. 82 tests passing.

**Held-out, opened here — moment 1 of the 4 that PRD §8 allows.**

```
heldout  seed 20260331  rungs R0+R1

  auto-match rate        80.43%   37 of 46 bank credits
  precision             100.00%   37 correct of 37 claimed
  recall                 84.09%   37 of 44 real matches
  payments covered       57.38%   2892 of 5040

  R0     32 credits     69.57%
  R1      5 credits     10.87%

  reconciled             ₹40,35,132.21
  open, received         ₹24,83,415.39   9 credits nothing explains
  open, expected         ₹29,27,818.40   27 settlements with no credit
  drift absorbed                 ₹1.55   4 matches consumed tolerance
  unexplained             ₹1,06,154.57   identity residue -- attribution is step 7
  run took 0ms  ·  model cost ₹0.00
```

`train` for comparison: 76.09% auto-match, 100.00% precision, 79.55% recall,
R0 52.17% / R1 23.91%, drift ₹1.33, residue ₹1,25,688.25.

**This is the baseline R2 is measured against.** `eval/results.json` is keyed set → rung
set → metrics, so step 6 writing `"R0+R1+R2"` cannot overwrite the `"R0+R1"` number it has
to beat. Acceptance criterion 9 gets its before/after with no field special-cased to hold a
previous run, and there is a test that the earlier key survives.

**The headline number is not the auto-match rate, it is payment coverage: 57.38%.**
80.43% of *credits* are matched, but only 57.38% of *payments* sit inside a matched credit,
because the 9 unmatched credits are disproportionately the bundled ones — a bundle carries
2–5 settlements and therefore several times the payments of a single-batch credit. Reporting
80.43% as "the match rate" would be technically true and misleading; the merchant's money is
in the payments. Both numbers are in `results.json` and both go in `EVAL.md`. R2's delta will
show up far larger on the payment number than on the credit number, and that is the honest
frame for it.

**R0's share moves 17 points between the two sets and the ladder is not why.** R0 is 52.17%
on train against 69.57% on heldout. The generator's UTR knob is identical for both; what
differs is bundling — 8 bundled credits on train, 6 on heldout — and a bundled credit fails
R0's amount test by construction. This is the step 4 prediction confirmed on data the engine
had not seen: R0's ceiling is the verbatim-UTR share minus the bundled share. It also means
any R0/R1 split quoted from a single dataset is noise at ±2 credits, which is worth
remembering before anyone reads §5's target table as a scoreboard.

**The conservation check got split in two, because one of the halves is not assertable yet.**

- *Assertable now:* the six CSV-derivable totals must reproduce the answer key's `totals`
  exactly. They do, on both sets, to the paisa. That is a real guard on ingest — it would
  catch a dropped row, a mis-parsed column, or a refund summed on the wrong side.
- *Reported, not asserted:* PRD §8's full identity leaves a residue of ₹1,06,154.57 on
  heldout. That residue is the injected damage. `world.assert_identity` runs on the **clean**
  world only, before `breaks.injure`, and breaks are money that no longer ties by definition
  — duplicate payments add gross, partial refunds move a batch net, an unidentified receipt
  adds a credit with no settlement behind it. Attributing the residue code by code is step 7,
  and it is exactly the check that will prove the classifier complete. Asserting it to zero
  today would mean either deleting the breaks or inventing an exemption.

The harness prints it as `unexplained` with that caveat on the line, rather than leaving it
out and letting the summary read cleaner than the books are.

**The partition check covers acceptance criterion 3 for what the ladder touches.** Every
bank credit and every settlement ends in exactly one state, no record ends in none, and the
credit rupees in each state sum to the rupees ingested. It runs on every eval and fails
loudly. It does not yet cover payments or orders — nothing assigns those a state until the
classifier exists.

**`in_transit_paise` comes from the answer key, and that is a temporary borrow.** It is the
one total in the identity that is not derivable from the CSVs, because deriving it needs a
period boundary the engine does not have until step 7. The harness may read it — reading the
answer key is the harness's job — but it means `unexplained` is not yet a number the engine
could produce on a real merchant's files. Flagged here so it is not quietly relied on.

**The no-float scan now covers `eval/` as well as `src/`.** The harness computes percentages
and rupee totals; that is a money path by any reading, and leaving it outside the scan would
have made `eval/` the obvious place for the first float to land. `bps()` rounds half away
from zero with integer arithmetic, matching `mul_bps`, and `time.monotonic_ns() // 1000000`
gives run latency in integer milliseconds where `perf_counter()` would have returned a float.
Third time the rule has been pressed, third time the code moved.

**Not reported, because it does not exist:** exception rate by code (classifier, step 7),
₹ discrepancy found (auditor, step 8), model cost (R3, step 9 — currently a hardcoded ₹0.00
so the field exists in `results.json` from the start). **p50/p95 latency is deliberately
absent**: the whole run is 0–1ms and there is no per-unit distribution to take percentiles
over until R3 introduces per-call latency that varies. Two identical percentiles of a
single-sample population is a metric shaped like a measurement. It lands at step 9.

**One field in `results.json` is not reproducible: `run_ms`.** Acceptance criterion 4 is
about the reconciliation output, and the reproducibility test asserts every field *except*
`run_ms` is identical across two runs of the held-out set.

---

## 2026-08-29 — Step 6a: decoy bundles, and a new baseline

Step 6 is split because regenerating the data invalidates the step 5 baseline (PRD §15).
This is 6a: the generator only. No solver was written.

**Held-out payment coverage 57.38% → 55.81%, R0+R1 unchanged.** That −1.57 point move is
the data, not the engine; nothing in `src/match/` was touched. **55.81% is the number R2's
delta is measured from.** The old 57.38% is dead and must not be quoted again — a delta
taken across a data regeneration measures the regeneration.

Auto-match rate held at 80.43% and precision at 100.00% on held-out.

### Control runs: what actually moved the number

Three controls, none of them written to `data/` — measurements, not datasets.

| | held-out | train | breaks (held-out) |
|---|---|---|---|
| **A** `_decoys` removed entirely — the pre-6a code path | 57.38% (2,892/5,040) | 56.05% (2,825/5,040) | 204 |
| **B** decoy rate 0 | 57.38% (2,892/5,040) | 56.05% (2,825/5,040) | 204 |
| **C** decoys built, protection disabled | 57.41% (2,896/5,044) | 56.10% (2,830/5,045) | 204 |
| **real** decoys built, protection on | **55.81%** (2,811/5,037) | **54.98%** (2,771/5,040) | 178 |

**A reproduces the old baseline to the payment.** The `_order_and_payment` refactor — optional
`amount`/`method`, returning the payment — consumes no randomness and changes nothing. That
is what makes the rest of this table readable.

**C − A isolates the decoy payments: +0.03 points held-out, +0.05 train.** Four added
payments, both of them inside credits that were already matched. The decoy construction
itself is very close to free.

**real − C isolates the protection filter: −1.60 points held-out, −1.12 train.** That is
the whole move.

**I had the mechanism wrong in the first draft of this entry and the control disproved it.**
I wrote that drawing for decoys shifts the RNG stream so break placement lands differently.
It does not: `build_dataset` gives injection its own generator, `Random(seed + 1)`, so the
world's RNG cannot reach it. What changed is the *populations* `_sample` draws from. The
protection filter removes records before sampling, so `rng.sample` returns a different subset
of a slightly different list — and E03/E04 drift, which lands on bank rows, is drawn from a
pool that lost exactly two refs and therefore selects almost entirely different credits.

**Most of the −1.60 is three credits, not a difficulty change.** Held-out, control against
real: three solo credits matched in the control are unmatched in real (45 + 50 + 137 = 232
payments), three different solo credits go the other way (51 + 51 + 45 = 147), and fifteen
more shift by ±1 or ±2 as duplicate payments move. Net −85 payments, which is the −1.69
points before the small gains. One of the lost credits carries 137 payments on its own. At
46 credits this is re-randomisation noise, not evidence the data got harder — note the real
run carries *fewer* breaks (178 against 204), which should make matching easier, not worse.

Worth remembering at 6b: a single solo credit swinging in or out is worth up to ~2.7 points
of payment coverage on this dataset. R2's delta has to be read against that.

### What broke first: a decoy that could be spotted by the size of one field

R2 spends no tolerance, so a decoy has to tie to the paisa. The first construction did it
with `adjustment_paise` — a real settlement field, signed, already inside PRD §8's identity
as `+ Σ adjustment`. Add the remainder R to one settlement's adjustment, its net, and the
single credit carrying it, and both sides of the identity move by R together.
`assert_identity` passed untouched and every settlement's own arithmetic still tied.

It was still wrong, and the measurement is why. The gap between a bundle and its nearest
rival subset, over both seeds:

```
Rs    162.84   Rs  2,117.03   Rs  2,705.61   Rs  2,935.02   Rs  3,214.90
Rs  5,134.72   Rs  5,993.98   Rs 10,202.58   Rs 18,919.45
Rs 62,787.44   Rs 1,36,248.07   Rs 2,59,613.44   Rs 2,89,939.94   Rs 3,25,367.86
```

Every other adjustment in the dataset lives between ₹1 and ₹500. A settlement carrying a
₹2,89,939.94 adjustment is findable by sorting one column, and the leak goes live the moment
any later rung or the fee auditor reads that field. Widening the candidate pool does not fix
it — the ±5 day window holds two to six spare settlements, and the worst gaps stay lakhs
wide. **Fewer decoys that read as ordinary beats more that do not.**

### What replaced it: choosing the contents

The decoy is a real subset of real settlements. The gap between its net and the target
credit is closed by adding ordinary payments — real orders, Indian names, pincodes,
whole-rupee prices, the usual method mix — to one settlement inside the decoy, with the last
one or two chosen so the total lands exactly. Fee and GST are computed the normal way, so
gross rises, fee and GST rise, and the credit rises by the net; both sides of the identity
move together and `assert_identity` never had to be loosened.

**The closing payment needs two payments, not one, and that is not obvious.** A settlement's
net carries sub-rupee digits because GST rounds on the fee, so the gap is almost never a
whole rupee — which rules out UPI, whose 0 bps fee makes its net contribution equal to its
amount. The fee-bearing methods do land on odd paise, but a payment's net rises monotonically
with its amount, so any one method hits about one paise value in a hundred. The first
implementation searched single payments and built **zero** decoys on both seeds. Searching
pairs against a precomputed net table reaches essentially every value, and it built 2 and 2.

Result, both seeds: every payment still priced in whole rupees (0 of 5,040 in paise), every
adjustment inside ₹43–₹495, decoy settlements holding 48–65 payments against a median of 56.
Nothing on any row marks a settlement as constructed. Two tests pin this.

### Feasibility is selected for, and the rate is reported as what it is

30% of bundled credits is the declared knob, but a five-day window with the true subset
removed leaves two to six spare settlements, and often none of their subsets sits near enough
*below* the target to close with a plausible number of payments — below, because payments
only add. Drawing blind gave 0 E14 on train. So feasibility is computed for every bundle
first and the 30% is drawn from the bundles that admit a construction; `decoys_attempted` and
`decoys_feasible` go in the answer key so `EVAL.md` can state the gap rather than imply the
rate was achieved by luck.

Both seeds landed 2 E14. PRD §8 asks for "two to three per run" and says to report the
population as too small to generalise from; on held-out that is **2 of 6 bundled credits**,
which is a proof that the path works and nothing more.

### Sequence, and why `breaks.py` had to change

Real bundles → decoys → `assert_identity` → `breaks.injure`. Decoys are a fact about how the
world is shaped, not damage, and they are built against known targets so they must come
after `_credits`.

That ordering means injection runs last and would delete the E14s. Fee variance alone samples
75 payments across 64 settlements, so nearly every settlement gets shifted; any shift to a
settlement in the true subset or the decoy subset moves one side of an engineered equality
and the ambiguity is gone with no trace. `world._decoys` records the settlements and credits
involved, and the four money-moving break functions sample from populations with those
removed. E06–E09 and E13 move no money and are left alone. `_assert_still_ambiguous` re-checks
every recorded subset after injection and **fails** rather than dropping — with two E14s in a
run, quietly discarding one discards a third of the population.

#### How big the shield is

| | train | held-out |
|---|---|---|
| settlements protected | 9 of 64 (14%) | 12 of 64 (19%) |
| payments inside them | 596 of 5,005 (11.9%) | 776 of 5,004 (15.5%) |
| linked refunds inside them | 12 of 176 | 32 of 185 |
| bank credits protected | 2 of 46 | 2 of 46 |

Breaks that would have landed on those records at the declared rates, measured by running
injection twice on the same seed with the shield off:

| Code | train | held-out |
|---|---|---|
| E05 fee variance | 75 → 66 (−9) | 75 → 63 (−12) |
| E10 duplicate payment | 40 → 35 (−5) | 40 → 33 (−7) |
| E11 partial refund | 35 → 32 (−3) | 37 → 30 (−7) |
| **total injected** | **200 → 183 (−17)** | **204 → 178 (−26)** |

So the shield costs 8.5% of train's breaks and 12.7% of held-out's. E03/E04 keep their counts
— the drift pool loses only the two target credits, too few to change `len(pool) * bps //
10000` — but they select a different set of credits, which is where most of the coverage move
in the control table comes from.

#### The structural note, and it is a real residual leak

**A bundled credit that carries a decoy now carries no breaks. A bundled credit without one
does.** Held-out: the two decoy bundles are protected 2-of-2 and 4-of-4 settlements, fully;
of the four bundles without a decoy, one has 2 of 4 settlements protected (they sit in a
decoy's subset) and the rest have none. Train is the same shape — both decoy bundles fully
protected, one of six others partly.

That correlation is discoverable. "The bundled credit whose settlements show no fee variance,
no duplicate payment and no partial refund is the ambiguous one" is a rule that would score
well on this dataset and means nothing on a merchant's. It is the same family of leak as the
`adjustment_paise` one that got the first construction thrown out, and it is not fixed — only
smaller, and made of an absence rather than an outlier, so no single column sorts it to the
top.

R2 cannot exploit it: the solver reads settlement nets and dates, never break labels, and the
labels do not exist in `data/` at all — they are in the answer key, which `src/` may not open.
But the exception classifier (step 7) and the fee auditor (step 8) both *derive* these breaks
from the CSVs, so a later rung that reads their output could correlate. **If R3 or any
later rung is given access to derived exception state, this is the first thing to check it is
not keying on.** Recorded here rather than fixed because the honest fix is more decoys across
more bundles, and the window does not offer them.

### The scoring rule the harness gained

PRD §8: an ambiguous credit is scored as a refusal. A claim on one is a **false** match even
when the payment set equals `true_subset`, because the engine had no evidence to justify
choosing it and would have been wrong as often as not on data the generator did not label.
Guessing correctly is not knowing, and a scorer that rewarded the guess would teach the
solver to guess. So ambiguous credits leave the recall denominator (44 → 42 real matches,
which is why recall rises 84.09% → 88.10% with the engine unchanged), and a claim on one
lands in the precision denominator without ever reaching the numerator. `ambiguous_claimed`
is printed loudly when non-zero. It is 0 today — R0 and R1 only ever match a single
settlement, so neither can reach a bundled credit. It starts meaning something at 6b.

`ambiguity_rate_bps` is reported even at zero, per PRD §12.

### PRD §5 corrected: R2 subset size is 2–5, not 2–4

6a found held-out carrying two size-5 bundles, which 2–4 made unsolvable by specification
while §8 declares `bundle_size` as [2, 5]. The old justification — "observed bundles are size
2 and 4" — was read off `SEED_TRAIN`, whose bundles happen to be exactly that. Held-out
contradicted it, which is what a held-out set is for. The combinatorial cost is nil: the ±5
day window leaves 2–6 spare settlements, so size 5 adds a handful of subsets.

`DECOY_MIN, DECOY_MAX` follow R2's parameters by definition — a decoy outside them is never
enumerated — so they moved to 2–5 too, and both seeds were regenerated. **The data did not
change.** Both size-5 bundles sit in three-settlement windows whose nearest rival subset is
₹1.27 lakh and ₹2.90 lakh below target, far outside the closable band, so `decoys_feasible`
stayed at 3 and 2 and the same four decoys were built. The baseline above is unaffected.

---

## 2026-08-29 — Step 6b: the R2 combination solver

`src/match/ladder.py` gains `r2`, `_pool`, `_exact_subsets`, `_witnessed`, `_claim_many` and
an `Ambiguity` record. `run(ledger, through=...)` stops early so the before/after numbers
acceptance criterion 10 wants come out of the same code rather than a remembered figure.

### The numbers

| held-out | R0+R1 | R0+R1+R2 |
|---|---|---|
| **payment coverage** | 55.81% | **90.89%** (+35.08) |
| auto-match rate | 80.43% | 93.48% |
| recall | 88.10% | 97.62% |
| precision | 100.00% | **95.35%** ← below the 99.5% bar |
| rung split | R0 32 / R1 5 | R0 32 / R1 5 / R2 6 |

Train: coverage 54.98% → 78.59%, auto-match 78.26% → 91.30%, precision 95.24%.

**The prediction, on the record beforehand, was 83.40% held-out and 72.40% train.** Held-out
came in at 83.42% before the window fix below — right to two hundredths. Train came in at
78.59% against 72.40% predicted, and the 6.19 point gap is exactly the 311 payments in the
two credits the answer key wrongly calls ambiguous: R2 matched them instead of refusing.
The part of the prediction that was reasoning about the solver held; the part that trusted
the answer key did not.

### R2's date window is ±6, not ±5, and ±5 was a train artefact

Held-out's `HDFC493525420` — a size-5 bundle carrying 376 payments — was unsolvable at ±5:
its earliest settlement sits 6 days from the credit, so the true subset was never in the
pool. Measured worst spans by bundle size, both seeds:

```
size 2:  3 days     size 4:  5 days     size 5:  6 days
```

±5 fitted train exactly, because train's largest bundle is size 4 and size-4 bundles top out
at precisely 5. **This is the same error as the subset-size line corrected earlier today, in
the same table, found the same way.** A size-N bundle spans N-1 settlement gaps on business
days, and one weekend inside those gaps adds two calendar days: 4 + 2 = 6 for size 5, which
is the observed maximum and the value now in the code, derived rather than fitted.

Worth ±7.47 points of held-out coverage (83.42% → 90.89%) and it cost no precision.

### Open defect: precision is 95.35% and the solver is not what is wrong

`tests/test_eval.py::test_heldout_precision_is_perfect_and_the_run_is_reproducible` is
**failing and has been left failing.** 91 tests pass, that one does not.

Both false matches are the two credits the answer key labels E14. R2 matched each to its
true subset. Under PRD §8 that is a false match by definition — the engine had no evidence
to justify choosing, so guessing right is not knowing. But R2 did not guess. It found
**exactly one** exact tie, because the decoy was not there to be found. Two separate reasons,
discovered in that order:

1. **The narration resolved it.** The target credit still carried a verbatim UTR naming a
   settlement inside the true subset, and PRD §5 explicitly permits that as a discriminator.
   An E14 the evidence resolves is not an E14 — §6 defines the code as the evidence *failing*
   to single out an answer. Fixed in `world._decoys`: the target credit is re-rendered
   UTR-absent through the same template the absent treatment uses, without touching `rng`.
2. **The ladder had already eaten the decoy.** This one is not fixed. Every decoy settlement
   is solo-credited, so R0 or R1 claims it against its own credit long before R2 runs. On
   held-out, 37 of 64 settlements are claimed by the time R2 starts, and of the two decoys,
   one has 0 of 3 members left open and the other 2 of 3. **A settlement that has its own
   bank credit cannot also be a rival for a different one**, and excluding claimed
   settlements from R2's pool is not a bug — it is acceptance criterion 3, which requires
   every settlement to end in exactly one state.

So the arithmetic ambiguity 6a built is real but inert: it exists among settlements that are
not available to be confused. The answer key claims an ambiguity the data no longer contains.

**What material a genuine R2 ambiguity would need**, measured on the open pool at R2 time:

| | held-out | train |
|---|---|---|
| settlements open when R2 starts | 27 of 64 | 28 of 64 |
| of those, inside some bundle | 22 | 24 |
| other (E02, in transit, unclaimed solo) | 5 | 4 |
| bundles with ≥2 *other* open settlements in window | 3 of 6 | 3 of 8 |

A decoy has to be built from settlements that survive to R2, which in practice means the
settlements of *other* bundled credits. That is feasible on 3 of 6 held-out bundles and 3 of
8 on train, before the gap even has to be closable — so the declared 30% knob may not be
reachable, and the honest outcome could be one E14 per run rather than two.

**Fixed by rebuilding the decoy, not by deleting the label.** Deleting the two `ambiguous`
entries would have read 100.00% precision immediately and left E14 with no generated data at
all — buying the number by removing the only case that tests the precision guard, against
PRD §6's rule that nothing sits in the taxonomy the generator cannot make. See the next
entry.

---

## 2026-08-29 — Step 6b, second pass: decoys that survive the ladder

`world._decoys` now draws its pool from the settlements that actually reach R2 — those inside
*other* bundled credits, which no single-settlement rung can claim, and those in transit,
which have no credit to be claimed against. The full reasoning is in `ARCHITECTURE.md`; the
short version is that a rival subset must survive the ladder to be a rival at all, and the
first design's decoys were dissolved by R0/R1 before the solver ever saw them.

### The numbers, on rebuilt data

| held-out | R0+R1 | R0+R1+R2 |
|---|---|---|
| **payment coverage** | 58.24% | **88.73%** |
| auto-match rate | 82.61% | 93.48% |
| recall | 88.37% | **100.00%** |
| precision | 100.00% | **100.00%** |
| E14 | — | 1 of 6 bundled credits, refused |
| rung split | R0 32 / R1 6 | R0 32 / R1 6 / R2 5 |

Train: coverage 52.24% → 86.97% (+34.73), precision 100.00%, recall 81.40% → 97.67%, E14 1 of 8.

Both seeds regenerated, so these baselines supersede the 55.81% / 54.98% figures recorded
earlier today. `results.json` holds both rung sets per seed.

**The E14 is live and the engine refuses it.** On both seeds the answer key's ambiguous
credit is exactly the credit `result.ambiguous` names, with two candidate subsets of size 2
each, and the trail reads *"2 different combinations tie to this credit exactly and the
narration does not single one out — E14, no match. Picking one would be a guess."* That is
the precision guard firing on generated data rather than on a fixture.

### The decoy rate is now a count, and PRD §8 says so

30% of bundled credits is not reachable. Measured across both seeds at ±6 days, exactly one
bundle per seed has a rival subset among R2-surviving settlements that can be closed with a
plausible number of payments. The knob is therefore declared as what it is — attempt every
bundled credit, build wherever a construction exists — and `EVAL.md` reports 1 of 6 held-out
and 1 of 8 train as a count with its denominator, with no ambiguity *rate* claimed from a
population of one.

**The fill ceiling was arbitrary and is now derived.** It was ₹25,000, chosen as "about
eighteen payments". The constraint that actually matters is that the host settlement stays
inside the natural spread, so the cap is now on payments rather than rupees: `DECOY_FILL_MAX
= 35` puts a median settlement at 91 against a natural 90th percentile of ~150 and a maximum
of ~240. Stating the bound in the units of the thing being hidden made the old ceiling
visibly too tight — it was the reason held-out's second candidate, needing ₹46,468, was
being rejected.

**One thing the in-transit host exposed:** `_credits` totals `in_transit_paise` before
`_decoys` runs, so filling an uncredited settlement left the identity off by ₹3,214.90.
`recompute_in_transit` now runs after decoys. `assert_identity` caught it on the first
regeneration, which is what it is for.

---

## 2026-08-29 — The pattern: parameters fitted to train, contradicted by held-out

Twice in one day, in the same table, found the same way.

1. **R2 subset size 2–4.** Justified as "observed bundles are size 2 and 4". True of
   `SEED_TRAIN`. Held-out has two size-5 bundles, which the rule made unsolvable by
   specification while §8 declared `bundle_size` as [2, 5].
2. **R2 date window ±5 days.** Justified as "at ±5, all 8 bundles solve". True of
   `SEED_TRAIN`, whose largest bundle is size 4 — and size-4 bundles top out at exactly 5
   days. Held-out's size-5 bundle sits 6 days from its credit and was silently unmatchable,
   worth 376 payments and 7.47 coverage points.

Both were written as though they were measurements. Both were fits to one sample, and in each
case the sample's ceiling was mistaken for the structure's ceiling. Neither would have been
caught by any amount of re-running train.

**The rule going forward: a parameter gets justified by the mechanism that produces it, not
by the range a dataset happened to show.** A size-N bundle spans N−1 settlement gaps on
business days, so a weekend inside those gaps adds two calendar days and size 5 reaches 6 —
that derivation predicts held-out's case without having seen it. "All 8 solve at ±5" cannot.
Where a number is genuinely empirical, it says so and names the population it was measured
on, which is the shape the decoy count now takes.

This will try to happen again at R3, where the temptation is a confidence threshold tuned
until train looks good. The threshold needs a reason, and the reason cannot be train.

---

## 2026-09-01 — A parameter restated is a parameter that drifts

Third and fourth instances of one failure mode in two days, so it gets a name instead of a
third one-off fix.

**The pattern:** a parameter has one value in code and its justification in several places.
The value changes. The primary justification gets updated. The restatements do not, and they
are indistinguishable from current fact to anyone reading them — including me, next session.

The four instances, all of them R2's window or subset size:

| # | Where the stale copy lived | Said | Actual |
|---|---|---|---|
| 1 | R2 subset size, fitted to train | 2–4 | 2–5 |
| 2 | R2 date window, fitted to train | ±5 | ±6 |
| 3 | `world.py` decoy-knob comment | "outside ±5 days … outside size 2-4" | 6, 2–5 |
| 4 | PRD §5 and §14, and `ladder._pool` | "6 of 8 unfiltered, zero filtered" | 2 of 8, 1 of 8 |

1 and 2 were the *fitting* error already written up. 3 and 4 are the *restatement* error, and
they are a different fault: the value was corrected, correctly, in the place that derives it —
and three other places kept the old number without contradiction from any test.

**Instance 4 is the one that mattered.** "With no date filter, 6 of 8 bundles admit more than
one valid subset; at a bounded window, zero do" was PRD §5's entire justification for bounding
the pool, and it was load-bearing for the design. Re-measured on current data today:

```
train    unfiltered 2 of 8 bundles      windowed 1 of 8
heldout  unfiltered 1 of 6 bundles      windowed 1 of 6
```

Both halves were wrong. Unfiltered is 2, not 6. Filtered is 1, not zero — because 6b's decoy
is built to sit inside the window, so the filtered count can no longer be zero by construction,
and the sentence had been asserting the opposite for two regenerations. The claim was measured
before 6a, at ±5 and size 2–4, on data regenerated twice since, and quoted forward each time
without re-running it. The conclusion it supports still holds — the filter, not the solver, is
what removes ambiguity, and on train it removes the one spurious collision and keeps the
engineered decoy — but it held by luck, not because anyone checked.

### The rule

**A number lives in exactly one place. Every other mention points at that place instead of
repeating it.** Where a second copy is genuinely unavoidable, a test asserts the two agree.

Applied here:

- `world.py`'s decoy knobs stay separate from `ladder`'s R2 constants on purpose — a generator
  that imports the matcher's constant makes every downstream test assert a variable equals
  itself. So the copies stay and `test_the_decoy_knobs_still_equal_r2s_own` binds them.
  Confirmed it fails on drift by setting `DECOY_WINDOW_DAYS = 5` and watching it fail, then
  reverting. **The test that would have caught instance 3 was already there and was asserting
  `world.DECOY_MAX` against `world.DECOY_MAX`** — a tautology with a docstring claiming it
  checked R2's filter. It now asserts against `ladder`.
- PRD §14 and `ladder._pool` no longer restate the window; both point at §5, which derives it.
- Every *measurement* now names the data it was taken on, so a regeneration invalidates it
  visibly rather than silently.

**And a step is not done until the docs are swept.** Added to the CLAUDE.md checklist: grep
for hardcoded windows, sizes and counts before calling a slice finished. Today's sweep found
exactly instances 3 and 4 and nothing else — the ±2 mentions for R0/R1 and the 2–5 bundle-size
mentions are all correct, and PRD §5's narrative of the fitting error is deliberately historical.

---

## 2026-09-01 — What the decoy rebuild cost, and what R2 is actually worth

Verification session. No engine code changed; the numbers below are re-runs, not new work.
Full suite 96 passed, 0 failed — including the E14 decoy tests that were left failing on
2026-08-29 and are now green because the decoy is real, not because the assertion moved.

### The precision trade, stated as a trade

Held-out, R0+R1+R2, before and after the decoy rebuild:

| | before rebuild | after rebuild |
|---|---|---|
| payment coverage | 90.89% | **88.73%** (−2.16) |
| precision | 95.35% | **100.00%** (+4.65) |

**Two and a bit coverage points bought four and a half precision points.** Before the rebuild
the decoys were inert — dissolved by R0/R1 before R2 ran — so R2 confidently matched the two
credits the answer key calls ambiguous, and those two matches were the entire precision
deficit. Rebuilding the decoy so it survives the ladder turns those into refusals: the coverage
they were carrying goes back to open, and precision goes to 100%.

This is PRD §5's "precision beats recall" showing up as a measurement rather than a stated
intention. It is also the direction the trade is supposed to run: the coverage given up is
coverage that was wrong.

### R2's delta, and one correction to how it gets quoted

On constant data — both figures on the current, rebuilt dataset:

| held-out | R0+R1 | R0+R1+R2 |
|---|---|---|
| payment coverage | 58.24% | **88.73%** (+30.49) |
| auto-match rate | 82.61% | 93.48% |
| recall | 88.37% | 100.00% |
| precision | 100.00% | 100.00% |

Train: 52.24% → 86.97% (+34.73), precision 100.00%, recall 81.40% → 97.67%.

**55.81% → 88.73% is not a constant-data delta and should not be quoted as one.** 55.81% was
the R0+R1 baseline on the *6a* dataset; 88.73% is on the 6b rebuilt dataset. A delta across
those two measures the regeneration as well as the solver — which is the rule the 6a entry
itself set down when it retired 57.38%. On constant data R2 is worth **+30.49 points** on
held-out, not +32.92. The larger number is flattering by 2.43 points of data change.

That correction is instance 5 of the entry above, caught by the entry above.

---

## 2026-09-01 — The pattern becomes a rule, and two more instances

The restatement entry above described a habit. It is now hard rule 7 in `CLAUDE.md`: **a
number that justifies a decision is re-measured when its data is regenerated, or it is
deleted.** Not updated-if-convenient — re-run or removed.

Two enforcement mechanisms, because five of the six instances were found by reading and only
one by a test:

1. **Provenance tags.** Every measured number in `PRD.md`, `ARCHITECTURE.md` and
   `EXPLAINER.md` now carries `*(dataset, step, date)*` inline. A number with a date is
   visibly stale-able; one without looks eternal. §5's dead figure was measured in chat on
   pre-6a data, was true when taken, was carried into the doc untagged, and nothing ever
   re-measured it — an untagged number gives a reader no reason to suspect it. An untagged
   number now means a derivation or a rule; if it is neither, it is suspect.
2. **An invariant test is not done until it has been watched failing.** Added to the how-to-work
   list. Break the guarded thing on purpose, run it, see it fail, revert, and state the break
   used. `test_a_decoy_is_a_different_subset...` asserted `world.DECOY_MAX` against
   `world.DECOY_MAX`, passed every run for two sessions, claimed in its docstring to check
   R2's filter, and **was counted in the pass total the whole time.** That is worse than no
   test: no test looks like no test, while a green tautology looks like coverage. The rule is
   cheap — one deliberate break per invariant — and it is the only thing that would have
   caught this.

### Instances 6 and 7, found by the sweep the rule now mandates

- **`EXPLAINER.md` Part 6 was built entirely on the retired numbers.** 80.43% / 84.09% /
  **57.38%** — the same 57.38% the 6a entry declared dead and said must not be quoted again —
  plus a section titled "Why payment coverage is only 57%" and the line "payment coverage is
  the number R2 exists to move", written before R2 existed. Re-measured and rewritten as the
  before/after it now is: 82.61% → 93.48% match rate, 58.24% → 88.73% coverage, recall 88.37%
  → 100.00% *(heldout, 6b, 2026-09-01)*. The narrative section now explains the +30.49 rather
  than the deficit.
- **PRD §9.1's close-summary mockup was unlabelled.** ₹68,42,100 reconciled, 96.2%, precision
  99.97%, R0 70.3% / R1 15.2% / R2 9.9% / R3 3.7% — all invented for the layout, none
  measured, and nothing on the page said so next to real measured figures elsewhere in the
  same document. Labelled: illustrative, no number in the block may be quoted as a result.

Neither was found by a test. Both were found by grepping the docs for digits, which is now
step one of the done-checklist.

---

## 2026-09-01 — The identity gap, measured: it closes to the paisa

At step 5 I wrote that the gap between PRD §8's two sides was "the injected breaks" and moved
on without measuring it. The data has been regenerated twice since. Same shape as §5's dead
justification — an assumption that was probably true when made, never checked, and quoted
forward. Measured now, per side, per paisa, both seeds.

**It reconciles exactly.** The residue equals the summed `delta_paise` of four codes with the
sign reversed:

```
                       train              heldout
harness residue        42,596,519         12,813,682
-(E01+E02+E03+E04)     42,596,519         12,813,682     ties, 0 unattributed
```

### Why those four, and why it is structural rather than a coincidence

Taking the identity apart after each break function, the codes fall into three groups and the
grouping follows from what each break does, not from what this run happened to produce:

| Group | Codes | Effect on `gross-fee-gst-refund+adj-in_transit` vs `credit` |
|---|---|---|
| **Bank side only** | E01, E02, E03, E04 | credit moves, left side does not → residue moves by the delta, opposite sign |
| **Both sides** | E05, E10, E11 | both move by the same figure → residue unchanged |
| **No money** | E06–E09, E12, E13 | linkage only, `delta_paise` is 0 → residue unchanged |

Worked through on train: E05 moves `fee +8,277 gst +1,490 in_transit −452` and `credit −9,315`
— the left side falls by 9,315 and so does the right, so it cannot appear in the residue.
E02 removes a credit row of ₹4,35,511.58 and touches nothing else, so it appears at exactly
that. The three both-sides codes carry ₹70,015.31 of movement on train and contribute nothing.

**The sides genuinely do not sum linearly, as expected.** The four bank-side codes push in
both directions — E02 −4,35,511.58 and E01 +9,904.26 on train — and the total break delta
across all thirteen codes (−3,55,949.88 train) is not the residue and never was. Only the
bank-side subset is.

### Two tests, both watched failing

`test_the_identity_residue_is_exactly_the_bank_side_breaks` and
`test_every_other_code_moves_both_sides_or_none`, parametrised over both seeds. The second
exists because the first alone would still pass if two both-sides codes broke in ways that
cancelled; it reverses the bank-side deltas out of the residue and requires zero.

Per the rule added earlier today, both were watched failing before being called done:

- **Dropped one E02 row from the answer key** → "22,349,248 paise are unattributed".
- **Relabelled one E10 as E01** → "99,105 paise … one of them is moving money on one side only."

Restored, 100 tests pass.

### Why this had to happen before step 7

The classifier's completeness claim is "every paisa of the gap traces to a code". That claim is
untestable against an identity that does not close, and unfalsifiable against a residue nobody
has attributed. Now the target is a fixed, verified number on both seeds, and step 7 either
reaches it or reports what it missed.

Queued for `EVAL.md` (step 13), and PRD §14 now requires the gap to be reported attributed
rather than as a lump.

---

## 2026-09-01 — Why the second identity test exists, and the general form of it

Worth separating from the entry above, because the reasoning outlives these two tests.

`test_the_identity_residue_is_exactly_the_bank_side_breaks` asserts one equation:
`residue == -(sum of E01,E02,E03,E04 deltas)`. It is a **sum over a population**, and a sum
hides cancellation by construction. If a both-sides code — E05, E10, E11 — started moving one
side only, it would inject an error into the residue; if a second both-sides code broke in the
opposite direction by the same figure, the two errors would cancel inside the total and the
assertion would still pass. The equation would hold while the claim it stands for was false.

`test_every_other_code_moves_both_sides_or_none` removes that hiding place from the other
direction: reverse the bank-side deltas out of the residue and require the remainder to be
**zero**, not merely consistent. Zero has no cancellation space — any single code moving one
side only shows up, whatever else is broken.

### The general form

**When an invariant is a sum over a population, one assertion on the total is not enough. The
total can be right for compensating wrong reasons.** Pair it with an assertion that has no
cancellation space — a zero, a per-item check, or a partition where every item lands in exactly
one bucket. Two tests, and the pair says which half failed.

This is the same failure the tautological decoy test had, in a different costume. That one
asserted something that could not fail; this one would assert something that could fail *and
still pass by luck*. Both report green. Both are worth less than the pass count suggests.

Where this applies next, unprompted:

- **Step 7's classifier.** "Every paisa of the gap traces to a code" is a sum. Two classifier
  errors of opposite sign in the same run cancel to a correct total. So the money figure gets
  paired with a per-code confusion matrix, where a misassignment cannot hide behind an equal
  and opposite one.
- **`check_partition`.** Already the right shape: it asserts set membership per record, not
  just that the rupees add up. Keep it that way.
- **Step 8's fee auditor.** An over-charge and an under-charge summing to zero is the obvious
  case, and the audit is worthless if it reports "no variance" on it.

---

## 2026-09-01 — E03 is raised by the ladder, not derived by the classifier

E03 is the odd one out among the four bank-side codes: E01, E02 and E04 are failures to match,
but E03 attaches to a match that **succeeded** within tolerance. A classifier that walks
unmatched records would never reach it, and would report zero E03 — which reads as "none in
this data" rather than "this path does not exist". A missing path that reports as a clean zero
is the tautological-test failure again.

**Decided: the ladder raises it, the classifier formats it.** Only the ladder knows a match
consumed tolerance; by the time the classifier sees the result, a flagged match and a clean
match look alike from the ledger. `Result.flagged` already holds exactly this population —
`Match.delta_paise != 0` — and CLAUDE.md rule 6 already requires every tolerance-consuming
match to be flagged and its drift counted.

Verified before deciding rather than assumed: the ladder's flagged set is **identical** to the
answer key's E03 set on both seeds — 5 of 5 on each, no misses, no extras *(train+heldout, 6b,
2026-09-01)*. Both E04s land in `unmatched_credits`, so they stay derivable from the ledger.

So the classifier has two sources, and the split is principled rather than incidental:

| Source | Codes | Why |
|---|---|---|
| The ladder's `Result` | E03 (`flagged`), E14 (`ambiguous`) | facts about the *matching attempt*, invisible in the ledger afterwards |
| The ledger | E01, E02, E04, E06–E13 | facts about the *records*, derivable without the ladder |

The test asserts E03 fires and that the emitted set equals the answer key's, so the path
failing silently is a failing test rather than a zero in a column.

---

## 2026-09-01 — Step 7: the exception classifier

`src/exceptions/classify.py`. Twelve of the fourteen codes raised, two deliberately not.
118 tests pass, up from 100.

### Per-code confusion, both seeds *(train+heldout, 6b, 2026-09-01)*

Counts, not rupees. E01 and E02 are ~99.9% of the identity gap, so a money-weighted
classifier score would be four rows in a trenchcoat — broad-looking accuracy that says nothing
about the other ten codes. The rupee figure stays in the identity check, where it means
something.

| code | train found/true/right | heldout found/true/right | note |
|---|---|---|---|
| E01 | 2 / 2 / 2 | 2 / 2 / 2 | |
| E02 | 2 / 2 / 2 | 2 / 2 / 2 | |
| E03 | 5 / 5 / 5 | 5 / 5 / 5 | raised by the ladder |
| E04 | 1 / 1 / 1 | 0 / 1 / 0 | held-out's only label is also an E01 — see below |
| E05 | — | — | step 8's audit owns it |
| E06 | 15 / 15 / 15 | 15 / 15 / 15 | |
| E07 | 16 / 16 / 16 | 15 / 16 / 15 | one amount collision with E06 |
| E08 | 3 / 3 / 3 | 3 / 3 / 3 | |
| E09 | 1 / 1 / 1 | 3 / 3 / 3 | |
| E10 | 38 / 38 / 38 | 36 / 36 / 36 | |
| E11 | — | — | not detectable from the CSVs |
| E12 | 2 / 2 / 2 | 2 / 2 / 2 | |
| E13 | 3 / 3 / 3 | 3 / 3 / 3 | |
| E14 | 1 / 1 / 1 | 1 / 1 / 1 | raised by the ladder |

Unclassified: **0 on both seeds**, reported on the summary line rather than in a footnote.

**Which codes are too thin to claim anything about.** Eight of the twelve have support ≤ 3 on
held-out — E01, E02, E04, E08, E09, E12, E13, E14 — and E04, E09 and E14 have a single row on
one seed or both. Those columns being green means the rule fired on one or two records; it is
not a rate and must not be read as one. The same reasoning as the precision denominator note:
a matrix where most classes hold a handful of rows can look perfect and mean very little. Only
E06, E07 and E10 (15–38 rows) carry enough to say the rule generalises, and E03 at 5 is
borderline. The harness prints the thin list every run so the number is never read alone.

### E11 cannot be detected, and that is a finding rather than a miss

A partial refund reduces the refund row **and** the settlement's `refund_paise` by the same
figure. Measured: settlements whose linked refunds disagree with their `refund_paise` — **0 of
64 on both seeds**, with 33 and 35 E11s present. No CSV field records what a refund was
originally raised for, so nothing in the merchant's export distinguishes a partial refund from
a smaller refund. This is the one place PRD §6's rule cuts the other way: the taxonomy requires
every code to be *generatable*, and this one is, but it is not *observable*. Stated in
`known_gaps()` and asserted by a test, so it reports as a known blind spot rather than a zero.

### E03 is raised by the ladder, E12 is a date fact, E10 names both rows

Three decisions where the honest answer differed from the convenient one.

- **E03** attaches to a match that succeeded, so a classifier walking unmatched records alone
  never reaches it. Raised from `Result.flagged`; the test asserts set equality with the
  answer key, not equal counts — equal counts of different records would pass a count check.
- **E12 comes before every matching consideration.** An in-transit settlement can also sit
  inside an E14's candidate subset, and an earlier version skipped it on those grounds and
  lost a real E12 on held-out. Whether a settlement is in transit is a fact about its date;
  nothing the ladder did may suppress it.
- **E10 names both payments.** They are identical by construction, so nothing in the ledger
  says which is the duplicate. The generator knows because it added one; picking the later id
  would be a guess wearing an answer's clothes.

### The in_transit borrow is retired

Flagged at step 5 as due at step 7. The period boundary is now derived from the bank statement
— a settlement dated after the last statement row cannot have been credited in it — and the
derived `in_transit_paise` ties to the answer key exactly on both seeds. That was the one total
in PRD §8's identity the engine could not produce on a real merchant's files. It can now.

### E07 costs one real row to avoid fifteen false ones

Unlinking a payment (E06) leaves its order looking unpaid, which is the same shape as a ghost
order (E07): 31 paid-orders-with-no-payment per seed against 16 real E07s. An orphaned payment
carrying exactly the order's gross is evidence they are one transaction, so the order is not
reported. That removes 15 false E07s per seed and costs 1 real one on held-out to an amount
collision. Precision over recall, and the cost is stated rather than absorbed.

### An answer-key defect, found by the classifier and not fixed

Held-out's single E04 label sits on `HDFC845765361`, which is **also labelled E01**.
`breaks._rounding_drift` draws from every credit row including the ones
`_unidentified_receipt` has just invented, so an invented credit was then drifted. A credit
that corresponds to no settlement cannot be an amount mismatch *against* that settlement — only
one of the two codes can be true, and it is E01. So held-out has no genuine E04, and the
classifier's "miss" is correct behaviour.

**Not fixed, deliberately.** The one-line fix in `breaks.py` is obvious, but it regenerates
both datasets, and hard rule 7 then invalidates every number measured today — the confusion
matrix above, the identity attribution, the R2 deltas, EXPLAINER Part 6. That is a re-measure
of the whole session, and it is the user's call whether it is worth making now or at the next
regeneration. Recorded here so it cannot be forgotten, which is the failure mode this rule
was written about.

### A tautology in a test written today, caught by today's rule

`test_an_unreadable_narration_is_e13_when_matched_and_e01_when_not` imported `AGGREGATOR` from
the module it was testing and checked the classifier agreed with itself. Changing
`AGGREGATOR = "RAZORPAY"` to `"NEFT"` left all 18 tests green. Rewritten to assert against the
answer key's E01/E13 sets; the same break now fails both seeds. **The rule caught a fresh
instance of the exact fault it was written for, in a test written an hour after the rule.**

Breaks used, all watched failing and reverted: E03 no longer raised from the ladder; the E12
period test disabled; `AGGREGATOR` changed; E14 relabelled as a break; `known_gaps()` claiming
a code the classifier does raise.

---

## 2026-09-01 — E11 is a limitation of the sources, not of the classifier

Reframed from an implementation gap to what it actually is, and moved into `ARCHITECTURE.md`
beside the rival-subset finding, because it is the same kind of thing: a fact about the
problem that is invisible from the code and expensive to rediscover.

**A partial refund cannot be detected from orders, payments, refunds, settlements and a bank
statement.** When a refund settles short, the refund row and the settlement's refund total
fall by the same figure. Every file stays internally consistent. The only evidence of the
break is what the refund was *originally raised for*, and no source carries it. Measured: 0 of
64 settlements show any inconsistency, with 33 and 35 partial refunds present
*(train+heldout, 6b, 2026-09-01)*.

A merchant who needs E11 needs a **fourth source** — the refund authorisation, carrying the
amount requested as distinct from the amount settled. Out of scope, and naming it is more
useful than silence.

### Why the code stays in the taxonomy

PRD §6's rule is that nothing sits in the table the generator cannot make. The converse — that
everything in the table must be detectable — is not a rule and must not become one by
attrition. Deleting E11 because nothing raises it would report a clean run on books that are
short by exactly the sum nobody is looking for. **This is the same defect E14 cost a session
to learn, arriving from the other side:** there, the answer key claimed an ambiguity the data
no longer contained; here, the engine would claim a completeness the sources cannot support.
Both are the report disagreeing with reality while every test passes.

So: §6 marks it undetectable by design with the reason, `known_gaps()` declares it in code, and
a test asserts it stays declared rather than drifting into an empty column.

## E04 is queued, not fixed

E11's handling turned out to be documentation only — it touches no generator code — so there is
no regeneration to ride along with. Per the decision to avoid a standalone regeneration, the
`_rounding_drift`-hits-an-invented-credit defect stays queued for the next regeneration that is
needed anyway. **The DECISIONS entry recording that held-out has no genuine E04 is the
artifact.** When that regeneration happens, `_rounding_drift` should exclude the rows
`_unidentified_receipt` appended, and every number measured on 2026-09-01 is re-run under hard
rule 7.

## The precision caveat now reprints with the number

`report()` prints, under precision on every run:

```
  precision             100.00%   43 correct of 43 claimed
                                  one wrong match here would read 97.67% -- a denominator of
                                  43, not a rate
```

Same reasoning as the thin-support list: a caveat that lives in a document can be separated
from the figure it qualifies, and 100.00% travels much better than its denominator does. At
~45 whole matches a single false match costs more than two points, so 100.00% is not
distinguishable from the value below it — and the run itself now says so. **A caveat that
reprints cannot be quoted out of context.**

---

## 2026-09-01 — Step 8: the fee variance audit, and a second number beside it

`src/audit/fees.py`. 131 tests pass, up from 118. E05 leaves `known_gaps()` — the audit owns it
now, and E11 is the only code that stays declared-undetectable.

### Checked first: the generator does not reverse MDR on refunds

Blocking check before any of this was built, because every figure below inherits it. `_refunds`
sets `status = "refunded"` and appends a row; it never touches `fee_paise` or `gst_paise`, and
`_settlements` sums fees across all payments regardless of refund status. Measured: **0 refunded
payments carry a reduced fee on either seed** *(train+heldout, 6b, 2026-09-01)*. The model
matches how Indian gateways actually behave, so the audit is measuring the real thing.

### Two numbers, and they are different in kind

| | train | heldout |
|---|---|---|
| **E05 overcharged** | ₹195.18 across 40 payments | ₹177.09 across 37 |
| **E05 undercharged** | −₹82.77 across 18 payments | −₹62.66 across 14 |
| net | ₹112.41 | ₹114.43 |
| **fee spent on refunded revenue** | ₹2,347.48 across 172 refunds | ₹2,536.59 across 179 |

**Over and under are printed separately, and the net third.** The generator injects both
directions and a real aggregator misconfigures in both, so a single net figure lets an
overcharge and an undercharge cancel into "no finding" — the same hiding place the second
identity test exists to close. Reporting only the net would have understated the finding by
₹82.77 on train.

**The refund burden is nine times the variance and is not a variance.** MDR is not reversed on
refunds in India, so every one of those charges is correct under the contract. It gets no
exception code deliberately: putting it in the exception list beside things that are wrong would
spend a controller's investigation on a correct charge. It is reported because a merchant
refunding heavily pays a real cost that appears in no statement as a line item. Nothing to
dispute — only to see. Counted only over refunds that join to a payment; an unlinked refund
(E08/E09) has no fee to attribute, which is 4 on train and 6 on held-out.

### The rate card is bound to PRD §7, not to the generator

The riskiest constant in the codebase, because two copies exist and **they are required to
disagree** — the generator injects variance against its own card, and that disagreement is the
entire signal. So both obvious tests are unavailable: binding the two cards asserts the audit
finds nothing, and asserting the card against itself is `DECOY_MAX == DECOY_MAX` in a new place.

`test_the_rate_card_is_the_one_in_the_prd` parses §7's code block and compares. The spec is the
single owner, and drift in either direction fails — verified both ways, by moving the code's
card and by moving the PRD's. A second test asserts nothing under `src/audit/` imports the
generator at all, mirroring the ground-truth guard.

`FEE_BPS` carries a provenance comment: these are a claim about a commercial contract, sourced
from PRD §7, never measured from the data, and *(PRD 7, 2026-09-01)*.

### Two more answer-key defects, found by the audit, queued not fixed

- **Phantom E05 labels.** `_fee_variance` clamps `max(0, old_fee + drift)`. UPI is contracted
  at 0 bps, so a negative drift on a UPI payment leaves it exactly on contract and records an
  E05 anyway. **15 of 71 on train, 18 of 68 on held-out** are labels for damage that was never
  done. Not audit misses — there is nothing in the ledger to find.
  *Nuance worth keeping:* train has 16 zero-delta E05 rows but only 15 phantoms. The 16th is a
  genuine variance on an in-transit settlement, where `delta_paise` is 0 because no credit
  moved. So zero-delta does not mean phantom; being on-contract does.
- **Duplicate-carried variance.** 2 on train, 1 on held-out. An E10 duplicate copies a payment
  that carried an E05, so the copy is genuinely off contract while only the original is
  labelled. The audit raising it is correct.

Both queued with the E04 defect for the next regeneration that is needed anyway. The test
scores against "labelled AND actually off contract" and asserts the phantom set is non-empty,
so if the generator is ever fixed the test fails and tells us to update it rather than quietly
passing.

### Two tests that passed for the wrong reason, caught by the watch-it-fail rule

- **`test_a_method_off_the_contract_is_refused_not_billed_at_zero`** used
  `pytest.raises(KeyError)`. Deleting the explicit guard left it green, because the bare dict
  lookup raises `KeyError` too. It tested the dictionary, not the guard. Now matched on the
  message; the same break fails.
- **An edit script wrote one test file's contents over another's path**, so `test_audit.py`
  briefly *was* `test_exceptions.py` and the suite reported 129 passing tests that included
  the audit file's tests twice and none of its own. Caught because the collected count moved
  from 13 to 18 without a test being added. Worth recording as the failure mode: a green suite
  whose *shape* changed is a signal, and the count is the cheapest place to see it.

---

## 2026-09-01 — Step 9: R3, and the prediction that held

139 tests pass, up from 131. **The prediction was recorded before any code was written: R3 adds
0.00 payment-coverage points on held-out.** It added 0.00.

| held-out | R0+R1+R2 | R0+R1+R2+R3 |
|---|---|---|
| payment coverage | 88.73% | **88.73%** (+0.00) |
| auto-match rate | 93.48% | 93.48% |
| precision | 100.00% | 100.00% |
| recall | 100.00% | 100.00% |
| rung split | R0 32 / R1 6 / R2 5 | R0 32 / R1 6 / R2 5 / **R3 0** |
| tokens | — | 1,833 (1,578 in / 255 out), ₹0 on the free tier |

Train: 3 credits offered, 0 accepted, 3,062 tokens. *(train+heldout, 6b, 2026-09-01)*

**The zero was structural and predictable, which is why it was predicted.** Held-out recall was
already 100.00% — every findable match was found — so R3's ceiling was zero by arithmetic
before a prompt existed. On train the four remaining credits were two E01s (no settlement
exists), one E14 (must refuse), and one E04 whose amount is ₹357.81 off, so the validator
rejects it at any confidence. There was nothing legitimate left to claim.

**Reported as the finding, not apologised for.** "We built the LLM rung, measured it against
the deterministic ladder, and it added 0.00 coverage points, and here is why" is a stronger
claim than any number that could have been manufactured — and it is exactly what PRD §15 put
the eval harness before the LLM to be able to say.

### The validator caught the model walking around acceptance criterion 8

The most important thing that happened this step. On the first live run, Gemini proposed a
match on `HDFC258778820` — the E14 ambiguous credit — naming two settlements at confidence 100.
The first version of the validator **accepted it**, because those two settlements do tie to the
paisa. Tying is necessary and not sufficient, and a validator that only checks the sum lets the
model route around R2's uniqueness guard entirely.

The first fix was wrong: re-run R2's enumeration at R3 time and reject if more than one subset
ties. It found one tie and accepted again. **The ambiguity had dissolved a rung later** — by the
time R3 runs, R2 has claimed the rival subset's members against their own bundled credits, so
only one subset is still open. This is the same "a rival must survive the ladder" effect as the
decoys, arriving one rung further on, and it means uniqueness at R3 time cannot see what R2 saw.

The guard that actually holds: **a credit R2 refused as E14 is never offered to the model.**
Only R2's refusal carries the information.

Worth recording plainly: the model's proposal was the *true* subset. It would have been "right".
PRD §8 still scores a claim on an ambiguous credit as false, and that rule is now vindicated
rather than theoretical — the rival was equally valid when the evidence was complete, and
guessing correctly is not knowing.

### No confidence threshold, and confidence turned out uninformative

The validator is binary and exact, so a threshold could only discard proposals before a free
check. Confidence is logged instead and its spread reported. Measured: **stated confidence
95–100 across every proposal on both seeds, including the one proposal the validator would have
been wrong to accept, at 100.** It does not discriminate at all on this data. Five data points
is far too few to claim a correlation and the harness says so rather than quoting one — but the
direction is worth having on the record, and it cost nothing to collect.

### Criterion 4, resolved by a committed cache

Flagged unresolved since step 5. Every response is cached on a SHA-256 of the exact prompt bytes
plus the model id, under `llm_cache/`, committed. Reruns call nothing. The criterion is restated
to what is true: identical inputs produce identical *accepted matches*, because the validator is
deterministic and the proposal layer is reproducible.

The larger win is not determinism: **a stranger can clone the repo and reproduce every number
with no API key**, which is acceptance criterion 11 in a form that survives us not paying an
API bill.

The cache lives at `llm_cache/`, not under `eval/`. The ground-truth guard fired when it was
first put there and it was right to: the cache is an *input* to the engine, and engine input
does not belong beside the answer key. A miss with no key raises rather than degrading — an R3
that quietly skipped its rung would report a zero that means "not run" and looks identical to
the zero that means "nothing left to find", and telling those apart is this whole step.

### The provider, chosen from the live list and then from what actually served

`gemini-3.7-flash` is the newest stable Flash in AI Studio's list, read on 2026-09-01. It and
`gemini-flash-latest` both returned HTTP 503 ("high demand … usually temporary") on every
attempt; `gemini-2.5-flash` is closed to new users. **`gemini-3.5-flash` is the newest that
actually served, so it is what the cache was built with.** Pinned rather than chained to a
fallback: a fallback makes the cache ambiguous about which model answered, and the two-provider
comparison depends on knowing exactly that. Transient 5xx gets three attempts.

### Explanations: judged now, on train, as the primary test

R3's matching ceiling is zero, so explanation is the job. Every proposal returned the code the
answer key carries — 3 of 3 on train, 2 of 2 on held-out — and every explanation named the
evidence and a next action. The E04 row, the hardest in the close:

> "The bank credit narration matches the UTR of settlement setl_s4l1ku1vti53ru, but the credited
> amount is short by 35,781 paise. Contact Razorpay support to obtain the breakdown of
> deductions, reserves, or adjustments applied to this settlement batch."

That names the settlement, the shortfall, and who to call. A controller reads it and knows what
to do, which was the bar set for this step. The E01s correctly say the row cannot be resolved
from these files and name what would resolve it — the bank's remitter details.

### Two more tautological tests, both caught by the watch-it-fail rule

- `test_the_prompt_is_built_from_the_taxonomy` iterated `TAXONOMY` and asserted each key
  appeared in the text `TAXONOMY` had just built. Renaming a key passed. Now bound to PRD §6's
  table — the same seam as the rate card and §7.
- `test_a_proposal_that_ties_is_accepted` searched the dataset for a credit with an
  exactly-equal open settlement, and asserted nothing on a seed where none exists. Replaced
  with two hand-built cases: a proposal that ties exactly at confidence 1 is accepted, and the
  same proposal one paisa out at confidence 100 is refused.

Breaks watched failing: the sum check removed; E14 credits offered to the model; R3 given
R0/R1's 100-paise tolerance; a code dropped from the prompt taxonomy; the cache key stripped of
its model id.

### Open: the Groq run has not happened

`GROQ_API_KEY` is not in `.env`, so the second provider is built and untested against a live
endpoint. The comparison that shows the validator rather than the model is doing the work is
therefore **not yet evidence** — it is a claim with one provider behind it. Add the key and
`PYTHONPATH=src uv run python eval/harness.py train heldout --r3 groq` populates
`llm_cache/groq.json`.

---

## 2026-09-01 — The coverage gap, attributed: the in-transit hypothesis does not hold

Measured before the UI work, because a metric the screens are built around should be understood
first. 141 tests pass, up from 139.

**The expectation was that the ~11% gap is dominated by in-transit settlements** — payments
correctly accounted for but not yet in a bank credit. It is not.

| bucket | train | held-out | what it is |
|---|---|---|---|
| **E02** | 292 (5.79 pts) | 108 (2.14) | settled, never reached the bank — money genuinely missing |
| **E12** in transit | 203 (4.02) | 229 (4.54) | normal at period end |
| **E14** | 110 (2.18) | 231 (4.58) | refused; one question settles it |
| **E04** | 52 (1.03) | — | money arrived, the figure is wrong |

*(train+heldout, 6b, 2026-09-01)*

In transit is **31% of the train gap and 40% of held-out** — a large minority, not the bulk. The
largest single bucket is E02 on train and E14 on held-out, and both are real: money that never
arrived, and a credit the engine refuses to guess at.

### The split ships anyway, and the strict number leads

The hypothesis was wrong about the proportion and right about the principle. A single figure of
88.73% invites the reading that 11.27% is *wrong*, and a settlement that lands after the
statement closes is not wrong — it is a clock, not a break. Conflating the two inside one number
is a real misreading, and it is worth four points of correction even though it is not worth
eleven.

So three buckets, with the strict number first and unsoftened:

```
reconciled to bank     88.73%   4470 of 5038   tied to a bank credit. THIS is the sign-off number.
in transit              4.55%   229 payments   settled after the statement closed
still open              6.73%   339 payments   and this is not one thing:
    E14      231     4.59%
    E02      108     2.14%
```

**"Still open" is deliberately itemised rather than totalled.** E02, E04 and E14 are three
different problems with three different actions — chase the processor, dispute a figure, answer
a question — and a controller reading one number does none of them.

### The finding worth more than the split

**On held-out a single refused credit holds 4.58 coverage points.** One E14 is 40% of that
seed's entire gap. Payment coverage is far more sensitive to one bundled credit than a
credit-level rate suggests, which is the same argument that made coverage the headline over
match rate in the first place — now pointing the other way, at coverage's own fragility. Any
coverage figure quoted from a seed with a handful of bundled credits carries that sensitivity,
and the split is what makes it visible instead of buried.

### The test

`test_the_coverage_split_accounts_for_every_payment` asserts the three buckets partition the
payments, that no uncovered payment reaches no code, and that the in-transit bucket is E12 and
only E12 — a leak there would report a real break as a normal period-end state, the one
direction that must not happen. Watched failing both ways: E14 settlements stripped of
attribution, and E02 folded into the in-transit bucket.


---

## 2026-09-04 — `ARCHITECTURE.md` written, before the screens

Written now rather than at step 13 because the material is freshest now and every screen makes
it vaguer. Docs slice only: no engine code touched, no number moved. 141 tests pass, held-out
re-run and every figure quoted in the document reproduces — 88.73% coverage, 100.00%
precision, 100.00% recall, rung split 32/6/5/0.

Structured around the decisions rather than the modules, per PRD §13. The sections that carry
the argument: the E14 incident on its own (the model proposed at confidence 100, the subset
tied to the paisa, the subset was the TRUE one, the validator rejected it anyway — being right
by accident is not knowing); "a rival subset must survive the ladder to be a rival at all" with
all three appearances, since it is a property of laddered matching rather than a generator
quirk; R3's 0.00 delta as a finding with its four-credit ceiling; the two priced precision
trades; and the fitted-versus-derived rule with the ±6 window as the worked example.

Every measured number carries its `*(dataset, step, date)*` tag, per hard rule 7.

### Two corrections made while writing, both from checking the source rather than remembering it

- **The confidence figure was about to be stated wrong.** The draft said the logged 100 was
  the E14 proposal the first validator wrongly accepted. It is not: the currently logged five
  are 95, 95, 95, 95 and a 100 on train's **E04**, which the validator refuses because the
  amount is ₹357.81 out. The E14 proposal was also at 100 but predates the guard and is no
  longer in the log — the guard means that credit is never offered. Both are now stated
  separately. The claim that survives is stronger, not weaker: *two* proposals most needed
  rejecting and both were stated at the top of the range.
- **"Six tautological tests caught by the rule" was an overcount.** Four: the `AGGREGATOR`
  import, the `KeyError` rate-card test, the prompt-taxonomy self-assertion, and the R3
  proposal test that asserted nothing on a seed lacking its case. One of the four was written
  an hour after the rule.

### What the done-checklist sweep found

**PRD §5's R2 parameter table restates `ladder.R2_WINDOW_DAYS` and `R2_SIZE_MIN/MAX` in prose,
and no test binds them.** The same seam is already bound in two other places —
`test_the_rate_card_is_the_one_in_the_prd` parses §7, and `test_propose` parses §6's taxonomy —
and `test_the_decoy_knobs_still_equal_r2s_own` binds the generator to `ladder`. §5 is the one
parameter statement with no such binding, which is precisely the shape of instances 2 and 3.

`ARCHITECTURE.md` now derives the window a third time, so it names `src/match/ladder.py` as the
value's only home and says explicitly that neither prose derivation owns it. That is a mitigation
and not the fix. **Not built, because it is an addition nobody asked for** — flagged for the
call. It is roughly the rate-card test with a different regex.

---

## 2026-09-04 — `ARCHITECTURE.md` revised: §0, §10, and one thing written as not-built

Six revisions, none touching §2–§8's substance. 141 tests pass, no engine code changed, no
number moved.

Added **§0**, orientation before the rung table — the five inputs, the six stages, and the three
words the document assumes (settlement batch, bank credit, and that one credit can carry
several batches, which is the reason R2 exists). The diagram is embedded there. Added a
five-line findings summary under the provenance note, anchored into the sections.

**The stale screen material in §9 is gone.** "A fourth screen" is now "a fourth view", the
argument reframed around views rather than React — it always was — and the run/upload
justification restated for a terminal. The **untagged 96%** went with it: it contradicted the
88.73% the document defends, which is exactly what hard rule 7 exists to catch. Cut rather than
re-measured, because the sentence works without a figure.

Epigrams thinned to four across the document. Cut "building the ladder first and the model last
is what turns AI judgment into a number" (§1 and §5 already make it, so it was a third
restatement) and un-bolded "it cannot see inside a library", which is a technical fact and reads
stronger as one.

### §10 documents ingest as it is, not as it was described

The revision brief described ingest as identifying files **by header signature rather than
filename**, with detection shown before the run commits and fieldnames stripped on read.

**None of that is built.** `SCHEMAS` is keyed by filename and `load()` does
`folder.joinpath(filename)`; `_read` matches columns by exact string against
`reader.fieldnames`, which are not stripped. Writing it as current behaviour would have put
fiction in the one document a reviewer reads to learn what is true.

So §10 states what ingest does — every bad row at once then load nothing, reject-unreadable
never reject-looks-wrong, values stripped — carries the padded-header incident as the worked
example of the loud failure being correct, and then records **both changes as known and not
made**, with the reasoning from the brief preserved as the argument for making them. The
fieldname strip is one line and has no argument against it. The header-signature change needs
detection printed and confirmed before the run commits, because silently deciding a file is the
refunds file is a silent inference in the one stage whose job is refusing to make them.

Recorded here because the deferred-work list already carried the fieldname asymmetry and now
two documents mention it. If either is built, both get updated.

---

## 2026-09-04 — Ingest identifies files by header, not by filename. Both changes taken.

The two changes §10 recorded as known-and-not-made earlier today are built. 150 tests pass, up
from 141. No engine code touched; every eval number is unchanged — held-out still 88.73%
coverage, 100.00% precision, 100.00% recall.

**1. Fieldnames are stripped on read.** One line in `_read`: `reader.fieldnames` is stripped
into a lookup before the absent-column check. Values were always stripped; headers were not, and
the asymmetry had no defence. A genuinely absent column still fails with the same message.

**2. `detect(folder)` identifies each CSV by header signature.** A file matches a schema when
its columns are a superset of that schema's required set. `load(folder, mapping=None)` takes
what detection produced, or falls back to the filename convention when given none — which is why
the harness, the match CLI and six test modules kept working untouched. That fallback is the
whole reason this was a thirty-line change rather than a refactor.

### The seam: pure detection, interactive CLI

`detect` prints nothing and asks nothing. Everything interactive lives in `src/ingest/__main__.py`.
Had the prompt gone into `load()`, the harness and 12 non-interactive callers would block on
stdin — the confirmation would have made the library unusable to everything except a person.

Detection is the **default** for `python -m ingest <folder>`. A flagged path is a path nobody
takes; building the merchant's route and then hiding it behind an opt-in would leave it
unexercised.

### Non-TTY proceeds; ambiguity never does

The prompt is skipped when `stdin` is not a terminal, and `--yes` skips it explicitly. The
confirmation exists to stop a person acting on a wrong reading, and a pipe has no person.
Refusing without one would make the merchant's path the one path CI never runs.

**But problems exit non-zero regardless of TTY.** Ambiguity is never resolved by the absence of a
human. Two files carrying one schema is a real choice a person can make, so with a terminal it
asks and without one it exits naming both. One file carrying two schemas is *not* a question
worth asking — it means the required-column sets do not discriminate, and any answer would be
the user guessing at our schema definitions. It exits, names the file and both schemas, and is a
signal to tighten a column set. That distinction is the E14 shape twice over: refuse when the
evidence does not single out an answer, and do not push a design problem onto the user as a
prompt.

### `matched on` — the table is evidence, not an assertion

Detection reports which required columns identified each file, using the ones unique to that
schema among all five (`captured_at, method` for payments; `refund_id, type` for refunds). Ten
characters of screen, and a reader can check the reasoning instead of trusting the answer — the
same reason every exception row carries the rung that gave up.

### Watched failing, all five

Per the rule. Each break failed exactly the test guarding it and nothing else:

- **Fieldnames not stripped** → the column-aligned detect/load test, the scruffy-equals-tidy
  test, and the padded-header test. 3 failed.
- **Silently take the first of two rivals** → `test_two_files_with_one_signature_are_a_choice_never_a_guess`.
- **One-file-two-schemas routed to `choices` instead of `problems`** → `test_one_file_matching_two_schemas_fails_rather_than_asking`.
- **`matched_on` emptied** → `test_detection_says_which_columns_named_each_file`.
- **Missing-schema problem suppressed** → `test_a_missing_signature_names_the_schema_and_the_columns_it_needed`.

The fixture is built at test time from `data/heldout` into `tmp_path` rather than committed:
junk filenames, one column-aligned header, one stray `notes.csv`. Committing a second copy of
held-out to test filenames would have put 3MB in the repo to assert something about strings.

**Retired from the deferred list:** the fieldname asymmetry recorded on 2026-08-29. `ARCHITECTURE.md`
§10 is rewritten in the present tense; the padded-header incident stays as the worked example,
because the fix is not leniency — what changed is only which files count as unreadable.

---

## 2026-09-04 — Step 10, in a terminal: the close, rendered

PRD §13 says `web/` and three screens. This is the same three screens in a terminal, at the
user's direction. Nothing about the engine changed to accommodate it: the render layer calls
`ingest.detect`, `ingest.load`, the four rung functions, `exceptions.classify` and the fee
audit, and turns what they return into characters. Session A is the entry, the run flow and the
primitives; the exception browser is Session B.

`src/tui/palette.py`, `src/tui/primitives.py`, `src/tui/__main__.py`, `tests/test_tui.py`.
26 tests, 176 in the suite. **No eval number moved** — `results.json` re-run on both seeds after
the change diffs to `run_ms` alone.

### `CONTEXT.md` does not exist

The brief cited "CONTEXT.md §7" for the six palette values. There is no such file in the repo;
the six values are PRD §10 and that is what was used. Flagged rather than guessed at, because a
seventh colour arriving through a document nobody can open is exactly the drift §10 forbids.

### Three deviations from PRD §10, all forced by the medium

Written down because each one *looks* like a palette violation and none of them is.

**`--paper` is never emitted.** The ground belongs to the user's terminal. Painting cream over
it fights their theme and leaves a rectangle in every screenshot.

**`--ink` is the terminal's default foreground, not `#14161A`.** Ink is "text and matched
figures" — which is to say the monochrome state, and a monochrome state has to be legible on a
light terminal and a dark one. `#14161A` on a dark ground is invisible. The terminal's own
foreground is correct on both by construction.

**`--rule` is dim rather than `#DEDEDA`.** A hairline has to sit *under* the text. `#DEDEDA` is
under ink on paper and over it on a dark ground, which inverts the hierarchy exactly where a
screen recording would show it.

`--muted`, `--open` and `--risk` go out verbatim as truecolour. They carry meaning; the other
three carry hierarchy, and hierarchy is what a terminal already has an opinion about.

### The level bar drops in-transit money entirely

First version drew three segments: received, then in-transit hatched, then the gap. On
held-out that made the ₹1,28,136.82 break draw as **zero cells** — 44 cells of bar, the credit
filling 43 of them, and the hatch taking the one that was left. The finding disappeared under
the thing that is not a finding.

The bug was in the semantics, not the arithmetic. Money settled after the statement closed is
not *expected in the period*: it is neither owed to this bar nor missing from it, and putting
it on the same axis makes a clock look like a break. So the bar is now two sides —
`expected − in_transit` against the bank credit — and the gap is the identity residue and
nothing else. In transit has its own bucket, hatched, uncoloured, three blocks down.

`sides()` derives in-transit from the classifier's E12 rows, not from the answer key, and
`test_the_level_bar_gap_is_the_identity_residue` asserts it equals the harness's
`unexplained_paise` — via `check_conservation`, not a written-down figure. A pinned number would
survive the next regeneration by describing the previous dataset, which is what the four
2026-09-01 entries are all instances of.

**And a shortfall now always draws at least one cell.** 0.02% of a crore is ₹2,000 and would
otherwise round to a bar that looks finished. `_span` has a floor for the same reason.

### The NO_COLOR bug the first test could not see

`test_no_color_env_is_honoured_on_presence` passed. Then the deliberate break — swapping
`os.environ.get("NO_COLOR") is None` for `not os.environ.get("NO_COLOR")` — **passed too**, and
the reason it passed is that the test only ever set `NO_COLOR=0`, where both readings agree.

Chasing that found the implementation was the wrong one. no-color.org specifies colour off when
the variable is present **and not empty**, and `is None` disables colour on `NO_COLOR=`, which is
how a user unsets it for one command without unsetting it for the shell. Fixed to
`not os.environ.get(...)`, and the test is parametrised over `0`, `1` and `""`. Both wrong
readings now fail on the case they get wrong, in opposite directions.

This is the second time on this project that a test which had only ever passed was asserting
nothing — the first was `test_a_decoy_is_a_different_subset`. The rule in `CLAUDE.md` caught
it. The rule is worth its cost.

### Watched failing, all six

- **`_span` floor removed** → the sub-cell shortfall test and the sub-cell bucket test. 2 failed.
- **Hatch painted with `pen.open`** → `test_in_transit_is_a_texture_and_never_an_accent`. E14 and
  in-transit are the two states where nothing is wrong with the money; neither may wear the
  colour that means something is.
- **`bps` floored instead of rounding half away from zero** → the parametrised rounding case and
  the harness-agreement test. 2 failed.
- **`coverage` mislabelled an E14 payment** → `test_the_rendered_coverage_split_equals_the_scored_one`.
- **`sides()` left in-transit inside the expected side** → the identity-residue test.
- **NO_COLOR, both wrong readings** → above.

### Two places this layer restates the engine, both guarded

`bps` and the coverage split are written twice, because nothing under `src/` may reference
`eval/` — the anti-circularity guard is a static scan for the name, and it is right to be. Two
copies of a rounding rule is precisely how a rendered percentage and a scored one drift apart,
so both copies are compared against the harness in `tests/test_tui.py` rather than trusted.

### What the close screen will not claim

Precision against ground truth needs the answer key, and this layer cannot read it — nor should
it, since a merchant running this on their own exports has no answer key either. The written
close says so and names the harness command instead of quoting a figure that would go stale on
the next regeneration. What it *can* prove from the run itself, it prints: every claimed match
ties to the paisa or inside tolerance, 5 consumed it for ₹2.83, one credit had a rival
combination and nothing was claimed on it, R3 spent 1,833 tokens and claimed nothing.

Thin support is reported the same way — over the codes *this run raised* three or fewer of,
which is a statement about the run rather than about the answer key.

### Skipped

**Typer.** `pyproject.toml` declares zero runtime dependencies and the CLI is two subcommands
and a menu. `sys.argv` covers it in ten lines. Add Typer when there is a third subcommand with
options worth parsing.

**Raw-mode keypresses.** Session A is `input()`; enter, `f`, `q` and `?` all take a return.
`j`/`k` in the exception list is what actually needs `termios`, and that is Session B.

**A float anywhere, including the animation.** The 400ms grow sleeps on
`timedelta(milliseconds=…).total_seconds()`. `10 ** -3` would have slipped past the no-float
scan just as quietly, which is the reason not to use it: the scan is only worth having if
nothing in `src/` is written to route around it.

---

## 2026-09-04 — Steps 11 and 12: the exception list and one exception opened

`src/tui/browse.py`, plus the design section `ARCHITECTURE.md` had been missing. 195 tests, 45
of them the render layer. **No eval number moved** — `results.json` re-run on both seeds and
through R3 diffs to `run_ms` alone.

### Two doc fixes, because the committed docs described things the code does not do

`PRD.md` is gitignored — `.gitignore` whitelists only `README.md`, `ARCHITECTURE.md` and
`DECISIONS.md` — so the six palette values and the rule governing them lived where a judge
cloning the repo could not read them. They are now `ARCHITECTURE.md` §10, with the accent rule
and the reason E14 is always `--open`: no money is at risk in an ambiguity, and painting a
question red tells a controller to panic about a decision. `CONTEXT.md` points there rather
than restating the hex, per §8's corollary.

The same section said in-transit money renders as a hatched outline on the level bar. It does
not, and the correction is written as a correction rather than a quiet edit, because the reason
is the interesting part: money settled after the statement closed is not expected in the
period, so it is not on that axis, and drawing it there was drawing a comparison that does not
exist.

### The list opens on everything. The argument for breaks-first is real and loses

**For:** a controller's first question is what is wrong, not what is unanswered, and PRD §6 says
burying a question inside a pile of problems wastes the attention the pile needs.

**Against, and decisive:** a default filter is invisible state. A reader who does not notice it
believes they have seen everything — the same class of error as a silent row drop, which is the
one failure this tool exists to refuse. The separation §6 asks for is achieved by the header,
which counts and prices breaks and questions apart, and by `/`, which is one keystroke and
leaves a visible marker in the footer when it is on.

### `r` opens the detail scrolled to the review prompt. It is not a second way to decide

A decision made from the list is a decision made on a code chip and a rupee figure. "Keep open"
requires a note, and a note written without the arithmetic on screen is a worse note. So `r`
skips the reading; it cannot skip the evidence. One code path writes `decisions.json`.

### The sort had to be defined before it meant anything

`delta_paise` is zero on **42 of 138** held-out rows — E06 to E09, E12, E13, and E14. Sorting
on it drops 30% of the list to the bottom in classifier order and puts the single
highest-leverage row in the run, the one question holding 4.58 coverage points, underneath 96
fee variances of a few rupees each.

**First attempt: fall back to the record's own amount for any zero-delta row.** Measured, and
worse — it sorted an E13 *second in the whole list* on ₹2,44,805 of money that had already
matched and was never at issue. "The amount on the record" and "the amount at stake" are
different quantities and only the second can be summed in a header.

**What shipped:** `abs(delta_paise)`, with E14 alone falling back to the credit it holds. One
special case, with a stated reason: E14's zero is a claim about risk, not about size. Every
other zero-delta code is genuinely holding nothing out of the close — E13 is an unreadable
narration on a credit that matched. The header's two totals are then the same quantity on both
sides, so it is a real total. Three tests pin all three halves.

### The offset row: built, wired, measured, deleted

PRD §10 puts it in the exceptions list on the argument that a scrolled list's ragged right edge
states the shape of the month before a figure is read. It was built, wired in at ten cells, and
**the edge is not ragged.** On this data a finding is either ~100% of its record (E01, E02, E10,
E14 — the money never arrived, or all of it is duplicated) or under 2% of it (E05, E03), with
nothing between. Every row renders as one of two shapes, and two shapes is a badge — which is
the thing §10's own rule forbids.

The first version of this entry kept `primitives.offset_row` and `browse.misalignment` unused
but tested, on the grounds that the measurement is a property of this dataset rather than of
the idea. That was the weaker version of the same story: **dead code in a repo a judge reads is
a claim the build is not making**, and an unused primitive says "we shipped the element"
while the list says otherwise. Both are deleted. The measurement moved to `ARCHITECTURE.md`
§10, beside the palette, where it reads as what it is — build it, measure it, report the number
that came out, the same posture as R3's delta of 0.00.

It cost four characters of reason text to find out.

### Detail scrolls rather than trimming

An E14 detail is 34 lines: the reason, the credit, the candidate stack with every settlement
inside every subset, the full R0→R3 trail, and the model's own words. It cannot be cut to 24 —
being the screen that shows all of it is the entire job — so `j`/`k` scroll it and the footer
counts what is below. Moving between exceptions is what the list is for.

### Watched failing, all seven

- **`weight` falling back to the record amount for every zero-delta code** → the E13 test and
  the sort test. 2 failed.
- **E14 sorting on its zero delta** → the E14 weight test and the sort test. 2 failed.
- **E10 marking the amount as the differing field instead of the id** → the duplicate test. The
  two rows agreeing on the amount is what makes one a duplicate; the accent must not point at
  the field that agrees.
- **The filter dropping the breaks/questions split** → two parametrised cases.
- **`decisions.json` written in place rather than by rename** → the atomic-write test.
- **A corrupt decisions file propagating** → a reviewer's judgment must not be able to stop a run.
- **The arrow table emptied** → the key test.

### Instance 6 of a number drifting, and the narrowest lesson yet

A new docstring wrote "4.59 coverage points" for what is 4.58. The uniqueness guard's cost is
the coverage *delta*, 88.73% → 93.31% = 4.58 points; E14's *share of payments* is 231 of 5,038
= 4.59%. Both figures already existed, both correct, one digit apart. Nothing downstream would
have failed and no test could have caught it — it was found by grepping the figure across the
docs before shipping, which makes it five of six instances found by reading.

`ARCHITECTURE.md` §8 now carries the lesson, which is narrower than "restating a number is
bad": **two quantities that round to neighbouring values are the hardest possible pair to keep
straight, because the wrong one never looks wrong.** Both now get named where they appear — the
delta is "coverage points", the share is "of payments" — and neither is written bare. The
count in `CLAUDE.md` and in the 2026-09-01 entry moved from five to six, which is the rule
applying to a number the rule itself produced.

### The menu loops, and a stray keystroke does not start a run

Three corrections after watching someone use it.

**A finished run is not the end of the session.** The first version ran once and exited.
Someone who has just watched the demo close is exactly the person who wants to point it at
their own exports next, and making them retype the command to do that is a step the program
can absorb. Every path now returns to the options, which reprint as "run the demo again".

**`q` runs nothing.** The first version fell through to the demo on any input it did not
recognise, so a stray keystroke started a 5,000-record run. Unrecognised input now reprints
the three options. Only an empty line runs anything.

**`folder >` did not say what it wanted.** It now states what the folder should hold, that
filenames do not matter because each file is identified by its headers, and that anything else
in the folder is skipped — with two examples. An empty line and a bad path both mean "go back";
neither is worth ending the session over. Quotes are stripped from the path, because dragging
a folder onto a terminal adds them and that failure would not have been the user's.

### Docker was built and deleted, for the reason the offset row was

It was added on the "runs on every computer" argument and removed on measurement. Two facts
killed it.

**The floor is Python 3.10, not 3.12.** The demo and all 199 tests pass on 3.10, 3.11, 3.12 and
3.13; only 3.9 fails, on `X | Y` in a signature. `requires-python` said `>=3.12` on nothing but
the version it was developed on, and now says `>=3.10` on a measurement. That is every current
Linux and any Mac with Homebrew Python — a much smaller gap than a container was being asked to
close.

**What is left of the gap, uv closes more cheaply.** macOS still ships 3.9 as `python3`. `uv`
is one curl command, needs no daemon, and fetches a Python itself; Docker is a much heavier
install plus a build. So the container bought nothing except for a judge who has Docker and
refuses uv, which is not a person.

**And it was never run.** There is no Docker daemon in the environment it was written in, so
what shipped was an unverified claim in a repo someone reads — the same objection that deleted
`primitives.offset_row` one session earlier, and the standard in `CLAUDE.md` is explicit:
never claim something works without having run it. The honest options were to verify it or
delete it, and deleting it also made the quickstart shorter.

`./barabar` absorbed the real problem instead: it searches `python3.13` down to `python3` for
anything ≥3.10, prefers uv where the project is present, and where nothing works prints the
version it found and the two ways out rather than a traceback about the `|` operator that
names no fix.

### `decisions.json`, and why it is not in `results.json`

A reviewer's judgment is not engine output. Mixing them means a rerun either clobbers the
judgments or inherits them as if they were measurements. Separate file, gitignored — it is
per-user state, not a deliverable — written to a temp path and renamed, so a half-written file
is never the state on disk. Keyed on `code:record_id`; the ceiling (two datasets sharing a
record id) is marked in a `ponytail:` comment rather than solved.
