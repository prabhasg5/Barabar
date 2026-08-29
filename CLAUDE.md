# Working agreement

Read `PRD.md` before doing anything. It is the spec. This file is how we work.

## What this project is

A settlement reconciliation tool for a hackathon whose judging criteria are, in order:
**problem taste, build quality, AI judgment, failure recovery.**

Every decision gets made against those four. A feature that does not change the number or make the number more trustworthy does not get built.

## Hard rules

1. **No floats in money paths.** Integer paise everywhere. Format to rupees only at render. There is a test for this; do not weaken it.
2. **The LLM never writes a match.** It proposes candidates; deterministic code validates the arithmetic and decides. There is a test for this; do not weaken it.
3. **The matching engine never reads the ground-truth file.** There is a test for this; do not weaken it.
4. **No silent row drops.** Malformed input fails loudly with row number and reason.
5. **Precision beats recall.** A false match hides a real break. When in doubt, leave it as an exception.
6. **Tolerance is never silent.** Flag every match that consumes it; report total drift per run.

## Scope discipline

Do not build, do not suggest building, do not scaffold "for later":
forecasting, tax matching, chat, auth, multi-tenancy, charts, donut graphs,
Tally/Zoho export, mobile app, live API integration, anything called "insights".

If you think something outside the PRD is needed, say so in one sentence and wait. Do not build it speculatively.

## How to work

- **Plan before code.** For any task over ~50 lines, state the approach in 3–5 bullets and wait for a go-ahead.
- **One vertical slice at a time.** Follow the build order in PRD §15. Do not start step N+1 while step N has no passing test.
- **Measure before and after every rung.** R2 and R3 each need a recorded delta. Run the eval, capture the number, write it to `DECISIONS.md` with the date.
- **Tests are part of the slice, not a later pass.** Especially the property-based invariant tests.
- **When something breaks, write it down.** `DECISIONS.md` gets an entry: what broke, what you changed, number before → number after. These entries are a graded deliverable, not a diary.

## Session protocol

Follow this without being asked each time.

**One step at a time.** Work the build order in PRD §15. Never start step N+1 while step N lacks a passing test. If asked to "build the thing", ask which step.

**Plan first.** For any task over ~50 lines, give 5 bullets and stop. Wait for a go-ahead before writing code.

**Measure at every rung.** Before adding R2 or R3, run the eval and record the current match rate in `DECISIONS.md`. Build the rung. Re-run. Report the delta. If the delta is small, say the small number — do not reframe it.

**After every step, unprompted:** run the eval, report the numbers, add a `DECISIONS.md` entry if anything broke or a number moved.

**Before adding anything not in the PRD:** state in one sentence why it is needed, then stop and wait. Do not scaffold it speculatively. The non-goals list in PRD §3 is binding.

## Known failure modes — self-check against these

You have specific tendencies on this project. Watch for them in your own output:

- **Reaching for a chart library.** There is one chart in this product, the level bar, and it is hand-drawn SVG. Do not install Recharts, Chart.js, D3, or anything similar.
- **Adding a fourth screen.** There are three. A fourth is always fluff.
- **Building a config system nobody asked for.** Hardcode until a second caller exists.
- **Creating `utils/`.** It becomes a junk drawer. Name modules for what they do.
- **Silently converting paise to float** in a formatting or display helper. This is the most likely bug in the project and the hardest to spot. The no-float test exists to catch it; never weaken or skip it.
- **Wanting to build the UI early** because it is more satisfying than the eval harness. The eval harness at step 4 is what the submission rests on. UI comes at step 9.

If you catch yourself doing one of these, say so and stop.

## Reporting style

- Report numbers, not adjectives. "Match rate 91.4%, up from 84.2%" not "significantly improved".
- If a result is worse than expected, say the number. Do not round up, do not reframe. Honest metrics are the explicit bar for this track.
- Never claim something works without having run it.

## Stack

Python 3.12 with `uv`. Typer for CLI. pytest + Hypothesis for tests. Anthropic SDK with structured output for R3 only.

Frontend: React + Vite + TypeScript, plain CSS with the tokens from PRD §10. No component library, no Tailwind config sprawl, no chart library.

Persistence: whatever is simplest that survives a restart and gives you atomic writes. Do not over-engineer this; it is not the graded part.

## Design

PRD §10 is the design spec and it is not a starting point to riff on. The palette is six values. The type is IBM Plex. Colour appears only for money states. If you find yourself adding a seventh colour or a gradient, stop.

**The visual grammar is one idea: two sides that either line up or they don't.** The level bar is the only chart in the product, reused at three scales. Do not add a second chart type. Do not render exceptions as badges, pills, or status icons — they render as misalignment. If a new UI element cannot be expressed as alignment or its absence, it does not belong.

Every numeral uses `font-variant-numeric: tabular-nums`. Money columns right-align and align on the decimal down the full column. This is functional.

## Before saying a slice is done

- [ ] It runs
- [ ] It has a test
- [ ] The eval still passes and the conservation check still holds
- [ ] `DECISIONS.md` updated if anything broke or a number moved
- [ ] Nothing outside PRD scope crept in
