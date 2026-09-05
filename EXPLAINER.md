# Barabar — what this actually is

Written for someone with no finance background. No jargon without a definition. Read it once end to end and the code will stop feeling arbitrary.

Current as of commit `b22b720`, step 5 complete.

---

# Part 1 — The finance, from zero

## 1.1 What happens when someone buys something online

You run an online store. A customer buys a ₹1,200 kurta.

You don't take their card details yourself — that's a legal and security nightmare. Instead you use a **payment aggregator**. In India that's Razorpay, Cashfree, PayU. They handle the card, the UPI, the bank, the fraud checks.

So the money goes: **customer → Razorpay → you.** Never customer → you.

That middle step is the whole reason this project exists.

## 1.2 Why the money arrives in lumps

Razorpay doesn't forward each ₹1,200 to you the moment it lands. That would be thousands of tiny bank transfers a day, which costs them money and clogs the banking system.

Instead they **batch** it. Roughly every day or two they take everything they've collected for you, do some arithmetic, and send you **one bank transfer.**

That single transfer is called a **settlement**.

So your bank statement doesn't say "₹1,200 from Priya, ₹899 from Rahul, ₹2,400 from Anjali." It says one line:

```
28/03/2026  NEFT-RAZORPAY SOFTWARE PRIVA-UTR849302175-HDFC   ₹4,32,187.55
```

That one number is 340 customers. And you have no idea which 340.

## 1.3 Why the lump isn't just the sum

Here's where it gets genuinely hard. That ₹4,32,187.55 is **not** the total of what your customers paid. Five things happen to the money on the way:

**Fees.** Razorpay takes a cut of every transaction — roughly 2% on cards, less on UPI. They deduct it before paying you.

**GST on the fees.** The government charges 18% tax on Razorpay's fee. That's also deducted. Note: GST on the *fee*, not on your sale. So a ₹1,200 sale with a ₹24 fee has ₹4.32 of GST on it, not ₹216.

**Refunds.** A customer returned something last week and you refunded ₹899. Razorpay already sent you that ₹899 in an earlier settlement, so they claw it back from this one.

**Chargebacks.** A customer told their bank "I didn't authorise this" and the bank forcibly reversed the payment. That money gets pulled back too, often weeks later.

**Adjustments.** Miscellaneous corrections. Small, irregular, and always annoying.

So the real arithmetic is:

```
what customers paid
  − Razorpay's fees
  − GST on those fees
  − refunds you issued
  − chargebacks against you
  ± adjustments
= the one number in your bank statement
```

**Everything in this project exists to run that equation backwards.**

## 1.4 What reconciliation means

Reconciliation is checking that two independent records of the same money agree.

Your systems say you should have received ₹4,32,187.55. Your bank says you received ₹4,29,347.55. Those two numbers must be **made to agree**, or you must be able to explain the ₹2,840 difference.

That's it. That's the entire discipline. "Barabar" — level, equal — is the state you're trying to reach.

When it works, accountants say the books **tie out**. When something can't be explained, that item is called a **break**.

## 1.5 Why anyone cares

Three reasons, in order of how much they matter to a merchant:

**You might be getting overcharged and not know.** Your contract says 2%. If Razorpay's system charges 2.3% on some transactions because of a misconfigured rate, you'd never notice. It's ₹3.60 per order. Across 5,000 orders it's ₹18,000. Nobody checks because checking means comparing 5,000 rows by hand.

**Settlements go missing.** A batch fails, gets stuck, or lands in the wrong account. If you're not reconciling, you find out months later or never.

**You legally have to.** Your accounts have to be auditable. "The bank sent us money and we assumed it was right" is not an audit trail.

## 1.6 How it's done today

A finance person exports three spreadsheets, opens Excel, and does VLOOKUP for two to three days a month. They match what they can, give up on the rest, and write off the difference as "bank charges."

That written-off difference is exactly the money this tool is designed to find.

---

# Part 2 — What Barabar does

## 2.1 The one-sentence version

You give it your orders, your payments, and your bank statement. It works out which orders are inside each lump-sum bank credit, tells you which ones it couldn't figure out and why, and tells you how much you were overcharged in fees.

## 2.2 The output that matters

Not the 96% that matched. **The 4% that didn't**, explained clearly enough that a human can deal with each one in under a minute — plus a rupee figure for money that leaked.

Matching is just how you get to the small pile that matters.

## 2.3 Why this is a good hackathon project

Razorpay has no reconciliation product — the obvious acquisition (Recko) went to Stripe. And they're currently hiring humans to do this work manually. You're automating something that is a live, unsolved, in-house pain at the company judging you.

---

# Part 3 — The five files

Your generator produces these. They mirror what a real merchant would export.

### `orders.csv` — 5,416 rows
What was sold. One row per order. Customer name, pincode, amount, status.
**Not all orders get paid** — some are abandoned. That's why there are more orders than payments.

### `payments.csv` — 5,040 rows
What was actually charged. One row per successful payment, linked to an order.
Carries the fee and GST Razorpay deducted, and which settlement batch it landed in.

### `refunds.csv` — 176 rows
Money you gave back. Links to an original payment.
These get subtracted from a future settlement, not the one the original payment was in — which is a common source of confusion and one of your exception types.

### `settlements.csv` — 64 rows
Razorpay's side of the story. "On this date we sent you ₹X, made up of these payments, minus these fees, minus these refunds." Each has a **UTR** — a Unique Transaction Reference, the banking system's tracking number for a transfer.

### `bank_statement.csv` — 46 rows
The bank's side of the story. Date, amount, and a **narration** — a messy machine-generated text string that may or may not contain the UTR.

## 3.1 The key asymmetry

**64 settlements, but only 46 bank rows.**

That's not an error. Some bank credits contain more than one settlement batch — the bank bundled them into a single transfer. In your training data, **8 of the 46 credits are bundles** carrying 2–5 settlements each.

Those 8 rows are the hard part of the entire project, and they're what step 6 exists to solve.

## 3.2 The narration problem

The bank's narration is a truncated machine string. Sometimes the UTR is right there. Sometimes it's cut off. Sometimes digits are transposed. Sometimes it's absent entirely.

Your generator controls this deliberately:

| UTR in narration | Share | Which method can handle it |
|---|---|---|
| Verbatim | 78% | R0 — exact match |
| Truncated | 12% | R1 — partial match |
| Garbled | 6% | R3 — needs AI |
| Absent | 4% | R3 — needs AI |

**This table is why your project has an AI component at all.** If every UTR were clean, exact matching would solve 100% of it and there would be no reason to use a model.

---

# Part 4 — How the matching works

## 4.1 The ladder

Four methods, tried in order, cheapest and most certain first. Each one gets a shot at what the previous ones couldn't solve.

| Rung | What it does | Uses AI |
|---|---|---|
| **R0** | Find the UTR in the narration. Check the amount matches to the paisa. Done. | No |
| **R1** | No clean UTR. Match on amount + date within 2 days + partial reference. | No |
| **R2** | This credit is a bundle. Which combination of settlements adds up to it? | No |
| **R3** | The text is mangled. Ask a model to read it and propose a match. | Yes |

**R0 and R1 are built.** R2 is next. R3 comes after.

## 4.2 Why "precision over recall"

Two words worth understanding properly, because they run the whole project.

**Precision** = of the matches you claimed, how many were right.
**Recall** = of the matches that existed, how many you found.

You want near-perfect precision and you're willing to sacrifice recall for it.

Why: a wrong match doesn't just fail to help. It **hides a real problem**. If you incorrectly tie a bank credit to the wrong settlement, the books look balanced, nobody investigates, and a genuine ₹40,000 shortfall goes unnoticed forever.

An unmatched item shows up as an exception and a human looks at it. A wrongly matched item disappears.

So the rule in your ladder is: if a credit has two plausible settlements, **match neither.** Your code does this — it's the `disputed` set in `Index`.

## 4.3 Why the AI can't be trusted with the answer

When R3 arrives, it will read mangled text and say "I think this belongs to settlement X."

It doesn't get to decide. It produces a *candidate*, and then plain deterministic code checks whether the amounts actually add up to the paisa. If they don't, the guess is discarded regardless of how confident the model claimed to be.

**The LLM proposes. Deterministic code disposes.** The model never writes a match.

This is the single most important design decision in the project, and it's what a Razorpay engineer will look for first.

## 4.4 Tolerance

Rounding means two sides can differ by a paisa or two legitimately. Your code allows up to 100 paise (₹1) of difference and still calls it a match.

But every match that uses that allowance is **flagged**, and the total absorbed is reported. Your current run absorbs 133 paise across 5 matches on train, 155 across 4 on held-out.

Why this matters: silently absorbing half a rupee four thousand times is ₹2,000 you invented from nothing. Reporting it is the difference between a tool and a liability.

---

# Part 5 — What you've built

## Step 1 — Money primitives (`src/money.py`)

All money is **integer paise**. ₹1,234.56 is stored as `123456`. Never a decimal.

Why: computers store decimals in binary approximately. `0.1 + 0.2` genuinely equals `0.30000000000000004`, so `0.1 + 0.2 == 0.3` is `False`. Your entire product is an equality test — "does this side equal that side." If `==` can't be trusted, nothing can.

Integers have no such problem. `8400 == 8400` forever.

Three functions:
- `Paise` — a type marker so the type checker knows what's money
- `mul_bps` — multiply by a rate expressed in **basis points** (a hundredth of a percent; 200 bps = 2%). Rates never enter the codebase as decimals, because `0.02` in a money path is exactly the bug you're guarding against. Rounds half away from zero so a fee and its reversal are equal and opposite.
- `format_rupees` — renders paise as Indian-grouped rupees. `4,32,187.55`, not `432,187.55`. Python's built-in `{:,}` groups in thousands, which is wrong for Indian readers.

And the guard: `test_no_floats_in_src` parses every module under `src/` and fails the build if it finds a float literal, a `/`, a `round()`, or the word `float`. Do not weaken it.

## Step 2 — Generator (`src/generate/`)

You need test data. You can't use a real merchant's — you don't have it, and it would be private financial records.

So you invent a business. **The generator is plain code — no AI anywhere in it.** Loops, seeded random numbers, arithmetic.

Two files:
- `world.py` builds a **perfectly tied** world where every settlement adds up exactly
- `breaks.py` then deliberately damages it, recording every injury as it makes it

**The key idea: because you created the data, you know all the right answers.** That's `eval/ground_truth/train.json` — your answer key. It contains 44 correct matches, 200 recorded breaks, the expected fee for every payment, and the parameters used.

The anti-circularity rule: **the matcher never reads the ground truth.** If it could, you'd be testing whether your code can read a file, not whether it can reconcile. There's a test enforcing this.

Two seeds: `train` (20260101) for development, `heldout` (20260331) for honest scoring. Look at held-out results only at steps 5, 6, 9, and 14 — otherwise "held-out" is just a filename.

## Step 3 — Ingest (`src/ingest/load.py`)

Reads the five CSVs. Normalises the deliberately inconsistent date formats. Converts rupee strings to integer paise.

Validates loudly: a malformed row fails with its row number and reason, and the whole run exits non-zero. It never silently skips a row — a reconciler that quietly drops records is worse than no reconciler.

## Step 4 — R0 + R1 (`src/match/ladder.py`)

The first two rungs. R0 pulls a verbatim UTR out of the narration and checks the amount. R1 falls back to amount + a ±2-day window + partial reference.

Two safeguards worth knowing:
- **One claim per settlement.** Once a settlement is matched, it's out of play.
- **Disputed settlements are locked out entirely.** If two credits both plausibly claim one settlement, that settlement is removed from *all* rungs — not just R0. Otherwise R1 would happily match what R0 correctly refused, and ambiguity would get laundered into a false confidence further down the ladder.

## Step 5 — Eval harness (`eval/harness.py`)

The spine of the project. It runs the matcher against the answer key and produces the numbers.

The scoring unit is the **whole match** — a credit tied to its settlements and through them to its payments. Four of five payments right is one *false* match, not four correct ones. Partial credit would let you claim accuracy you don't have.

It also runs the conservation checks: every record ends in exactly one state, and the counts and rupee totals tie back to what was ingested.

---

# Part 6 — Your numbers, explained

From `eval/results.json`, held-out set. Both columns are the same code on the same data —
`run(ledger, through=...)` stops early — so the delta is R2 and nothing else.
*(heldout, 6b, 2026-09-01)*

```
                     R0+R1      R0+R1+R2
auto-match rate     82.61%       93.48%    (38 -> 43 of 46 bank credits)
precision          100.00%      100.00%    (every claimed match correct)
recall              88.37%      100.00%    (38 -> 43 of 43 findable matches)
payment coverage    58.24%       88.73%    (2,934 -> 4,470 of 5,038 payments)
absorbed drift                 283 paise   (5 matches consumed tolerance)
```

## Why precision is 100%

Every match you claimed was right. That's the number that matters most, and it's the one that lets you say the tool is trustworthy. Keep it there.

## Why match rate (93.48%) and recall (100.00%) differ

There are 46 bank credits but only **43 findable matches.** Three credits are deliberately unmatchable: two are `E01` breaks — unidentified receipts, money that arrived from something other than a Razorpay settlement — and one is the `E14` ambiguous credit, where two different combinations of settlements tie to it exactly and nothing in the narration says which. The tool refuses that one on purpose.

So match rate measures you against all credits including the impossible ones. Recall measures you against what was actually achievable. Recall is the fairer number, and reporting both is the honest thing to do. Recall at 100% means every match that could be found was found; the 6.52 points of match rate you are "missing" is the tool correctly declining to invent three answers.

## Why payment coverage moved 30 points

**This is the important one**, and it is the clearest thing R2 did.

At R0+R1 you matched 82.61% of credits but only 58.24% of payments. That gap existed because the 8 credits left unmatched were disproportionately the bundled ones — a credit containing 4 settlements carries roughly 4× the payments of a single-settlement credit — so an unmatched minority of credits held a large chunk of the money.

R2 solves exactly those: which subset of settlements sums to this credit. Five bundled credits, 1,536 payments, **+30.49 coverage points** *(heldout, 6b, 2026-09-01)*. Credit count is a flattering denominator and payment coverage is the honest one, which is why the two moved by such different amounts — 10.87 points of match rate against 30.49 of coverage.

## What the run cost

`model_cost_paise: 0`. No AI has been used yet, and 93% of the credits — 89% of the money — are already done. When R3 arrives, you'll be able to state precisely what the model added and what it cost. That comparison is the strongest thing you can put in a submission.

---

# Part 7 — What's next

## Step 6 — R2, the combination solver

**The problem:** a bank credit of ₹4,32,187.55 doesn't correspond to any single settlement. It's a bundle. Which combination of your 27 unmatched settlements adds up to it?

This is a **subset-sum problem** — given a list of numbers and a target, find the subset that sums to it. It's a classic algorithm, and it's solved with dynamic programming or meet-in-the-middle, not by brute force over every combination.

**Do not use AI for this.** It would be slower, cost money, give different answers on different runs, and be less accurate. Solving it deterministically and saying so in your architecture doc is a deliberate signal about AI judgment.

**The critical constraint:** a bundle must have **exactly one** valid combination. If two different subsets both sum to the target within tolerance, match neither. Same precision-over-recall logic — an ambiguous bundle is an exception, not a coin flip.

**How to run the session:**

```
Record the current held-out numbers in DECISIONS.md.
Step 6 only: R2 combination solver. Pure algorithm, no LLM, no I/O,
nothing outside src/match. Plan it in 5 bullets, then stop.
```

Then afterwards:

```
Run the eval on held-out. Show me the delta on all four numbers.
```

**What success looks like:** payment coverage moving from 57% to somewhere near 90%, precision staying at 100%. If precision drops, R2 is guessing and needs its uniqueness check tightened.

## The remaining steps

| Step | What it adds |
|---|---|
| 7 | Exception classifier — every unmatched item gets a code and a rupee delta |
| 8 | Fee variance auditor — the headline rupee number |
| 9 | R3, the LLM rung, plus its validator |
| 10–13 | The three screens |
| 14 | Hardening review |
| 15 | Docs, deploy, video |

**After step 9 you have a submittable project.** CLI only, no interface, but with measured accuracy, an honest exception list, a rupee finding, and a documented argument about where AI earned its place. That already clears the bar the track states. Everything after is upside.

---

# Part 8 — The exception codes, in plain English

Your generator produces all thirteen. Here's what each actually means, with how many appear in your training data.

| Code | Count | What it means |
|---|---|---|
| **E05** | 75 | **Fee variance.** Razorpay charged a different rate than your contract says. This is your money-finding code. |
| **E10** | 40 | **Duplicate payment.** The same order got charged twice. |
| **E11** | 35 | **Partial refund drift.** A partial refund's arithmetic doesn't tie exactly. |
| **E07** | 16 | **Order says paid, no payment exists.** Note: an *unpaid* order is just an abandoned cart, not an exception. Only orders whose status claims paid. |
| **E06** | 15 | **Payment with no order.** An orphan — money arrived for something not in your order book. |
| **E03** | 5 | **Amount mismatch within tolerance.** Matched, but flagged, and its drift counted. |
| **E13** | 3 | **Unparseable narration.** The bank text is unreadable. R3's territory. |
| **E08** | 3 | **Refund with no original.** A refund that doesn't link back to a payment. |
| **E12** | 2 | **Period cutoff.** Paid in March, settled in April. Not an error — a timing difference — but it must be identified as one. |
| **E02** | 2 | **Settlement with no bank credit.** Razorpay says they sent it; the bank has no record. The most serious code on this list. |
| **E01** | 2 | **Bank credit with no settlement.** Money arrived that isn't from Razorpay. |
| **E04** | 1 | **Amount mismatch outside tolerance.** A real break. |
| **E09** | 1 | **Chargeback debit not in your books.** Money was pulled back and your system doesn't know why. |

E14 (currency mismatch) was deleted. A rupee-only D2C merchant has no foreign exchange line, and a code that exists for completeness rather than because the domain has it is padding.

---

# Part 9 — Glossary

**Aggregator / payment gateway** — the company between you and the customer's bank. Razorpay.

**Settlement** — one batched transfer from the aggregator to your bank account.

**UTR** — Unique Transaction Reference. The banking system's tracking number for a transfer. Your primary matching key.

**Narration** — the free-text description on a bank statement line. Machine-generated, often truncated.

**Chargeback** — a customer disputes a payment with their bank, and the bank forcibly reverses it.

**Reconciliation** — checking that two independent records of the same money agree.

**Tie out** — accountant's phrase for two sides agreeing exactly.

**Break** — an item that doesn't tie and can't yet be explained.

**Basis point (bps)** — one hundredth of a percent. 200 bps = 2%. Used so rates can be integers.

**Paise** — 1/100 of a rupee. The smallest unit, so all money can be stored as whole numbers.

**Precision** — of the matches you claimed, the share that were correct.

**Recall** — of the matches that existed, the share you found.

**Subset-sum** — given a list of numbers and a target, find which subset adds to the target. What R2 solves.

**Held-out data** — test data you don't look at while developing, so your final number is honest.

---

# One thing to check

The clean-world identity doesn't tie exactly in `ground_truth.json` totals:

```
gross − fee − gst − refund − adjustment = 731,815,775
credit + in_transit                     = 719,285,610
gap                                       12,530,165 paise  (₹1,25,301.65)
```

That gap is *approximately* accounted for by the E02 breaks (₹1,33,720 of settlements that never reached the bank) net of the E01 unidentified receipts (₹8,520). So it's almost certainly working as designed — the breaks are supposed to break the identity.

But "almost certainly" isn't good enough for a reconciliation tool. Ask Claude Code to show you the exact per-side reconciliation of that gap and confirm every paisa of it is attributable to a recorded break. If it is, that's a good line for `EVAL.md`. If it isn't, you've found a real bug while it's still cheap to fix.
