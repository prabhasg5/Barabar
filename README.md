# Barabar

**Settlement reconciliation for Indian D2C merchants.** Ties lump-sum bank credits back to the
individual orders inside them, explains everything that does not tie, and puts a rupee figure
on money lost to fee errors.

*Barabar* means level — two sides that come out the same. "Hisaab barabar" is the everyday
phrase for accounts settled.

---

## The problem

A merchant sells 340 items in a day. The money does not arrive as 340 payments. It arrives as
**one bank credit** — say ₹4,32,187.55 — because the payment aggregator nets everything:
payments, minus fees, minus GST on those fees, minus refunds, minus chargebacks, minus
adjustments.

The merchant cannot answer the only question that matters: **is that number right?**

Today the answer is one finance executive with three spreadsheets and VLOOKUP, two to three
days a month, who eventually gives up and accepts the number. Fee overcharges, missing
settlements and unlinked refunds go unfound because nobody has time to look.

**Who it is for:** the finance executive, or the founder's CA, at a D2C brand on Razorpay. One
person. Once a month. Under time pressure.

**Their job:** close the month, and be able to defend the close.

---

## What this does

Five CSVs in — orders, payments, refunds, settlements, bank statement. Out comes a close
summary and a short list of everything that did not tie, each row explained well enough to act
on in under a minute.

**The output that matters is not the 88% that matched. It is the rest, explained** — plus a
rupee figure for money the merchant lost without knowing.

---

## Quickstart

Three commands. Needs Python 3.12 and [uv](https://docs.astral.sh/uv/). **No API key, no
network.** The dataset and every model response are committed.

```bash
uv sync                                                    # install (pytest + hypothesis only)
uv run pytest -q                                           # 150 tests
PYTHONPATH=src uv run python eval/harness.py heldout       # score against held-out ground truth
```

That last command prints the close. Nothing else needs to run.

<details>
<summary>Other commands</summary>

```bash
# Regenerate the synthetic data from seed (both datasets are already committed)
PYTHONPATH=src uv run python -m generate train
PYTHONPATH=src uv run python -m generate heldout

# Ingest only. Files are identified by their headers, not their names: it prints what it
# detected with the columns that identified each one, then asks before it commits.
# The prompt is skipped when stdin is not a terminal; --yes skips it explicitly.
PYTHONPATH=src uv run python -m ingest data/train

# The rung split and absorbed drift
PYTHONPATH=src uv run python -m match data/train

# Include the LLM rung, served from the committed cache
PYTHONPATH=src uv run python eval/harness.py heldout --r3 gemini
```
</details>

---

## What you will see

Real output from the third command, not a mockup:

```
heldout  seed 20260331  rungs R0+R1+R2

  auto-match rate        93.48%   43 of 46 bank credits
  precision             100.00%   43 correct of 43 claimed
                                  one wrong match here would read 97.67% -- a denominator of 43, not a rate
  recall                100.00%   43 of 43 real matches
  payments covered       88.73%   4470 of 5038
  ambiguity rate         16.67%   1 of 6 bundled credits have a rival subset

  -- how it was matched --
  R0     32 credits     69.57%
  R1      6 credits     13.04%
  R2      5 credits     10.87%
  R3      0 credits      0.00%

  reconciled             ₹62,01,045.22
  open, received          ₹2,92,494.02   3 credits nothing explains
  open, expected          ₹7,62,608.10   6 settlements with no credit
  drift absorbed                 ₹2.83   5 matches consumed tolerance
  unexplained             ₹1,28,136.82   identity residue -- all of it E01/E02/E03/E04, asserted by test_eval

  -- where the payments are --
  reconciled to bank     88.73%   4470 of 5038   tied to a bank credit. THIS is the sign-off number.
  in transit              4.55%   229 payments   settled after the statement closed
  still open              6.73%   339 payments   and this is not one thing:
      E14      231     4.59%
      E02      108     2.14%
```

Two things about that output are deliberate.

**The precision caveat reprints with the number.** 100.00% on a denominator of 43 is not
distinguishable from the value below it — one wrong match would read 97.67%. A caveat that
lives in a document gets separated from the figure it qualifies. This one cannot be quoted out
of context.

**The gap is itemised, not totalled.** 88.73% invites the reading that the other 11.27% is
*wrong*. It is not one thing: a settlement that lands after the statement closes is a clock,
not a break, and E02 (money that never arrived), E04 (money that arrived at the wrong figure)
and E14 (a question, not a problem) need three different actions.

---

## How it works

![Architecture diagram](Architecture_diagram.png)

The diagram above is the whole system: five CSVs in on the left, the ladder falling through the
middle, the LLM off the main line behind a validator, and the generator and ground truth walled
off at the bottom where the engine cannot reach them. What follows is a walkthrough of each
piece.

> **[→ Read `ARCHITECTURE.md`](ARCHITECTURE.md)** for why it is shaped this way — the reasoning
> behind each rung, the incident that produced the validator, the two precision trades and what
> they cost, and the trade-offs that were considered and rejected.

**Ingest** identifies each CSV by what its header contains rather than by its filename — a
merchant's exports are named whatever their aggregator named them — and prints what it decided,
with the columns that identified each file, before it commits to anything. It then normalises
three date formats and parses money into integer paise. It validates in one pass and reports
*every* bad row with its row number and reason — then loads nothing. First-error-and-stop makes
fixing a file an N-round trip; load-the-good-ones produces a confident close that is wrong by
however many rows were dropped.

It rejects rows it cannot *read*. It never rejects a row that merely looks wrong — a payment
with no order, a refund with no payment, a settlement with no credit are the findings, not
errors.

**The matching ladder** is four rungs, each one trying to tie a bank credit to the settlement
batches inside it and through them to the payments inside those. Each rung passes down only
what it could not claim.

| Rung | Method | LLM |
|---|---|---|
| **R0** | Exact: a verbatim UTR in the narration names a settlement, and the amount ties | no |
| **R1** | Composite: amount within ±₹1, a ±2 day window, a partial reference | no |
| **R2** | Combination: which subset of still-open settlements sums to this credit, exactly | no |
| **R3** | Narration parsing, entity resolution, explanation | yes |

Cheapest-first is not about compute — R2 finishes in milliseconds and R3 costs ₹0 on the free
tier. It is about **evidential strength**. R0 matches on two independent facts agreeing, which
is hard to do by coincidence. R2 matches on a sum, and a sum has combinatorially many ways to
be produced. Running strong evidence first means weak evidence is only ever asked about records
the strong evidence could not explain — the smallest possible surface for a false match.

**R2 spends no tolerance and requires uniqueness.** A bundle ties to the paisa or it is an
exception, because every paisa of slack is a window that any of hundreds of subsets can fall
into. And if *two* subsets tie exactly, R2 returns no match and raises E14 carrying every
candidate, so a reviewer can see what the choices were.

**The exception classifier** codes everything the ladder left, from two sources. Facts about
the *records* come from the ledger. Facts about the *matching attempt* — a match that consumed
tolerance, the rival subsets behind an ambiguity — vanish from the ledger once the ladder
finishes, so those are raised by the ladder itself.

**The fee audit** recomputes every payment's fee and GST from the contracted per-method rate in
integer basis points, and compares. Over- and undercharges are reported separately, because a
single net figure lets them cancel into "no finding".

---

## The four rules

Each one has a test that fails if it is weakened.

**1. No floats in money paths.** Integer paise everywhere, formatted to rupees only at the
render boundary. The guard parses every module under `src/` and `eval/` and fails on a float
literal, a `/`, a `round()`, or the name `float`. This is also why there is no pandas: its
numeric core is float, a paise column silently becomes `float64` on one `.mean()` or one
NaN-bearing join, and the guard cannot see inside a library. `dependencies = []`.

**2. The LLM never writes a match.** It proposes; deterministic code validates the arithmetic
and decides.

**3. The matching engine never reads the ground-truth file.** The generator writes it, the eval
harness reads it, nothing under `src/` may open it. Otherwise the eval measures the engine
rediscovering its own rules.

**4. Precision beats recall.** A false match hides a real break and someone signs off on wrong
books. Where evidence is ambiguous, no rung guesses.

---

## Three findings

### The LLM proposed a match at confidence 100. It was right. The validator rejected it anyway.

On the first live R3 run the model proposed a match on the credit R2 had already refused as
ambiguous, naming two settlements, at confidence 100. The first validator **accepted it** —
those two settlements do tie to the paisa.

The proposal was the true subset. The model was right.

It was still wrong to accept. R2 had refused that credit because *two* distinct subsets tie to
it exactly and nothing chooses between them. The model picked one. It had no information R2
lacked — it had less, because R2 had enumerated both. A validator that only checks the sum lets
a model walk straight around the uniqueness guard, most convincingly in exactly the case where
the guard was doing the most work.

**Tying is necessary and not sufficient. Being right by accident is not knowing.**

The fix that worked is not a better check at R3 — it is that a credit R2 refused is never
offered to the model at all. By the time R3 runs the ambiguity has already dissolved, because
R2 has claimed the rival's members against their own credits. Only R2's refusal carries the
information.

### The LLM rung added 0.00 coverage points, and that is the result

Predicted before any R3 code was written, and it landed exactly *(heldout, 6b, 2026-09-01)*.

Held-out recall was already 100.00% after R2 — every findable match had been found — so R3's
ceiling was zero by arithmetic before a prompt existed. Train had four credits left, and all
four were unreachable by anything honest: two where no settlement exists to match, one that
must be refused, and one whose amount is ₹357.81 out so the validator rejects it at any
confidence.

Reported as the finding, not apologised for. **This is why the eval harness was built before
the LLM** — so "what did the model actually add" has an answer rather than an assumption.
R3's real job is explaining the four hardest rows in the close, and it does that well:

> "The bank credit narration matches the UTR of settlement setl_s4l1ku1vti53ru, but the
> credited amount is short by 35,781 paise. Contact Razorpay support to obtain the breakdown of
> deductions, reserves, or adjustments applied to this settlement batch."

### One exception code is undetectable from these five files, and it stays in the taxonomy

E11 is a refund that settles for less than it was raised for. The remainder is money the
merchant is owed and does not have.

When a refund settles short, the refund row **and** the settlement's refund total both fall by
the same figure. Every file stays internally consistent, because nothing in any of them records
what the refund was originally raised *for*. Measured: 0 of 64 settlements show any
inconsistency, with 33 and 35 partial refunds present *(train+heldout, 6b, 2026-09-01)*.

It stays in the taxonomy, marked undetectable, declared in code by `known_gaps()` and asserted
by a test. Deleting it because nothing raises it would report a clean run on books that are
short by exactly the sum nobody is looking for. A merchant who needs E11 needs a fourth source:
the refund authorisation, carrying the amount requested as distinct from the amount settled.

---

## Measured results

Two seeds. `heldout` is opened at four moments in the build and nowhere else — a held-out set
consulted on every iteration is a training set with a misleading name.

Each dataset: ~5,040 payments across 64 settlement batches and 46 bank credits, over 3 months.

*(train+heldout, 6b, 2026-09-01)*

| | held-out R0+R1 | +R2 | +R3 | train R0+R1 | +R2 | +R3 |
|---|---|---|---|---|---|---|
| **payment coverage** | 58.24% | **88.73%** | 88.73% | 52.24% | **86.97%** | 86.97% |
| precision | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% |
| recall | 88.37% | 100.00% | 100.00% | 81.40% | 97.67% | 97.67% |
| rung split | 32/6 | 32/6/5 | 32/6/5/**0** | 23/12 | 23/12/7 | 23/12/7/**0** |

**Payment coverage is the number to quote, not the credit match rate.** One unmatched bundled
credit carries several settlements' worth of payments, so a flattering credit-level rate can
sit on top of a large share of missing money. The merchant's money is in the payments.

### The rupee findings

| | train | held-out |
|---|---|---|
| fee overcharged vs contract | ₹195.18 across 40 payments | ₹177.09 across 37 |
| fee undercharged | −₹82.77 across 18 | −₹62.66 across 14 |
| **fee spent on refunded revenue** | **₹2,347.48 across 172 refunds** | **₹2,536.59 across 179** |

The second number is nine times the first and **is not an error**. MDR is not reversed on
refunds in India, so the gateway keeps its fee whether or not the sale survives. Every charge
there is correct under the contract. It gets no exception code deliberately — putting it beside
things that are wrong would spend a controller's investigation on a correct charge. It is
reported because it is a real cost that appears in no statement as a line item. Nothing to
dispute, only to see.

---

## What is built, and what is not

| | |
|---|---|
| ✅ | Money primitives, integer paise, no-float guard |
| ✅ | Synthetic generator + ground truth, two seeds |
| ✅ | Ingest: header-signature detection, normalisation, loud validation |
| ✅ | R0 + R1 + R2 + R3 and the validator |
| ✅ | Eval harness, conservation and partition checks |
| ✅ | Exception classifier, 12 of 14 codes raised, 2 declared blind |
| ✅ | Fee variance audit + refund fee burden |
| ⬜ | **The three screens.** Nothing is rendered yet — this is a CLI and an eval harness. |
| ⬜ | Review decisions persisted between runs |
| ⬜ | `make demo`, deploy |

**Known gaps, stated rather than hidden:**

- **The Groq run has not happened.** The second provider is built behind the same
  `call(prompt, provider)` interface but has never been run against a live endpoint, so the
  two-provider comparison is a claim with one provider behind it, not evidence.
- **Three answer-key defects are queued, not fixed.** Held-out's only E04 label is also labelled
  E01 and only one can be true; 15–18 E05 labels record damage that was never done because a
  clamp left UPI payments exactly on contract. Fixing them means regenerating both datasets,
  which invalidates every number on this page. They are recorded in `DECISIONS.md` and ride
  along with the next regeneration that is needed anyway.
- **E11 is never raised** — it cannot be, from these sources (above). E04 *is* raised and correct
  on train (1 of 1); the one it misses is held-out's mislabelled row, where reporting nothing is
  the right answer.

---

## Repo layout

```
src/money.py        Paise, mul_bps (integer basis points), format_rupees
src/generate/       the synthetic world and its answer key   -- never read by the engine
src/ingest/         parsers, date/money normalisation, loud validation
src/match/          the ladder: R0, R1, R2, R3, and the validator
src/propose/        the LLM interface, prompt, and prompt-hash cache
src/exceptions/     the taxonomy applied to whatever the ladder left
src/audit/          fee and GST variance against the contracted rate
eval/               the harness, ground truth, results.json
data/               both generated datasets, committed
llm_cache/          every model response, keyed by prompt hash, committed
tests/              150 tests, unit and property-based
```

Further reading in the repo: **[`ARCHITECTURE.md`](ARCHITECTURE.md)** is the decisions and the
trade-offs rejected. **[`DECISIONS.md`](DECISIONS.md)** is the dated build log — what broke,
what changed, number before → after.

---

## Reproducibility

Every model response is cached on a SHA-256 of the exact prompt bytes plus the model id, under
`llm_cache/`, and committed. Reruns call nothing.

So identical inputs produce identical *accepted matches* — the validator is deterministic and
the proposal layer is reproducible — and more usefully, **a stranger can clone this repo and
reproduce every number on this page with no API key at all.**

A cache miss with no key raises rather than degrading. An R3 that quietly skipped its rung would
report a zero meaning "not run", indistinguishable from the zero meaning "nothing left to find",
and telling those two apart is the whole point of that rung.

To run it live instead, copy `.env.example` to `.env` and add a Google AI Studio key.

---

## Design of the numbers

Two conventions this project holds to, both of which cost something.

**Every measured number carries a `(dataset, step, date)` tag.** A number without one is a
derivation or a rule. This exists because five numbers here survived a data regeneration by
being quoted forward instead of re-run — a tagged number is visibly stale-able, an untagged one
looks eternal.

**A parameter is justified by the mechanism that produces it, not by the range one dataset
showed.** R2's date window is ±6 days because a size-N bundle spans N−1 settlement gaps on
business days, and one weekend inside those gaps adds two calendar days: 4 + 2 = 6. It was
originally ±5, fitted to a training set whose largest bundle happens to be size 4. Held-out had
a size-5 bundle carrying 376 payments sitting 6 days from its credit — silently unmatchable,
worth 7.47 coverage points.

---

MIT licensed. Built for the Razorpay AI Buildathon, Track 04.
