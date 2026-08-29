# Prompts

For you, not for Claude. Copy-paste these. `CLAUDE.md` handles the standing rules; these are the moments where a specific prompt does better than a general rule.

---

## Session start

```
Read PRD.md and CLAUDE.md. Don't write code yet.
Tell me what's ambiguous or underspecified, and what you'd push back on.
```

Do this once, before any code exists. Fixing the spec is cheaper than fixing the build.

Every subsequent session:

```
Read PRD.md, CLAUDE.md and DECISIONS.md. Tell me where we are and what step is next.
```

---

## Starting a step

```
Step <N> only: <name>. Plan it in 5 bullets first, then stop.
```

Never "build the project". Never two steps at once.

---

## Finishing a step

```
Run the eval. Give me the numbers. Add a DECISIONS.md entry.
```

---

## Before R2 (the combination solver)

```
Record the current match rate in DECISIONS.md.
Now build R2 as a pure algorithm — no LLM.
Re-run the eval and show me the delta.
```

---

## Before R3 (the LLM rung)

```
Record the current number in DECISIONS.md first.
Then add the R3 LLM rung with the deterministic validator.
I want the honest delta even if it's small.
```

If the answer comes back as an adjective instead of a number, ask again.

---

## When it wants to grow

```
Is this in the PRD? If not, one sentence on why it's needed, then wait.
```

---

## Weekly review

```
Review the whole repo against the four criteria in CLAUDE.md.
Where would a Razorpay engineer lose trust?
```

Run this even when nothing feels wrong. It surfaces things a step-level review misses.

---

## When something breaks

```
Don't fix it yet. What broke, and what's the smallest change that fixes it?
```

The failure itself is a graded deliverable. Capture it before you patch it.

---

## Before the deadline

```
Read EVAL.md and the metrics in results.json.
Write the README problem statement: the person, what they do today, the rupee cost.
Three sentences, no product description.
```

---

## Reality check

`CLAUDE.md` reduces drift. It does not eliminate it. Over a long session, context fills and the rules get further from the model's attention.

So:

- Start a fresh session per step rather than one long session for everything
- If a reply ignores a `CLAUDE.md` rule, say `check CLAUDE.md` rather than re-explaining the rule
- When answers get vague or it starts agreeing with everything, that's the signal to restart the session
- Read the diffs. The rules catch tendencies, not every mistake.
