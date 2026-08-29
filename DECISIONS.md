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
| 6 ⬜ | **Next: R2 combination solver.** Held-out opens again there. |

82 tests passing. No known failures, nothing skipped except the two dataset tests when
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
train    seed 20260101   5,040 payments  64 settlements  46 bank rows   8 bundled credits
                         200 breaks: E01 2  E02 2  E03 5  E04 1  E05 75  E06 15  E07 16
                                     E08 3  E09 1  E10 40  E11 35  E12 2  E13 3
heldout  seed 20260331   5,040 payments  64 settlements  46 bank rows   6 bundled credits
                         204 breaks
ingest   5416 orders  5040 payments  176 refunds (185 heldout)  64 settlements  46 bank rows
```

**Held-out, R0+R1: auto-match 80.43% (37 of 46 credits), precision 100.00%, recall 84.09%,
payment coverage 57.38%.** Train: 76.09% / 100.00% / 79.55% / 56.05%. Payment coverage is
the number R2 has to move — the unmatched credits are the bundled ones, which carry several
times the payments of a single-batch credit. Baseline is in `eval/results.json` under
`R0+R1`.

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
- **`data/` and `eval/ground_truth/` are committed-by-default and not gitignored.** Decide
  whether generated data belongs in git before the first commit.
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
