# 010 — Break Cause mis-attribution: only prefix-bearing fields can explain a break

**Status:** change 1 (ordering) done 2026-08-28 · change 2 (allow-list) open,
blocked on evidence · **Priority:** 1 (corrects a shipped headline number)

## Context

`explain_breaks()` tested `turn_context_changes()` first, before the TTL branch,
and still diffs *every* field of `turn_context` except `turn_id`. Both choices are
wrong, and together they moved a seventh of the corpus into the wrong bucket. The
ordering is fixed (see Decisions); the field selection is not.

Census over the corpus (392 Sessions, 475 Cache Breaks, 25.8M Re-billed):

| Break Cause reported | breaks | re-billed | share |
|---|---:|---:|---:|
| TTL expiry | 123 | 12.8M | 49.6% |
| turn_context change | 59 | 4.6M | 18.0% |
| mid-turn history change | 194 | 3.1M | 11.8% |
| turn-boundary history rewrite | 56 | 2.5M | 9.6% |
| unknown | 35 | 2.1M | 8.1% |
| cache warm-up | 8 | 0.7M | 2.9% |

Of the 59 `turn_context change` breaks, **32 (3.79M Re-billed — 14.7% of the
corpus total) also satisfy the TTL test**. The `turn_context` branch runs first
and claims them. For 16 of those (1.77M) the only field that moved was
`current_date`, so the reported cause is literally *the date is different* when
the actionable truth is *you resumed a Session that had been dead for days*.

Every one of the 20 `current_date`-only breaks is a multi-day resume
(`07-11 → 07-13`, `08-15 → 08-18`, `04-02 → 04-04`) with an Idle Gap of at least
7.4 hours. **There is not one mid-Session midnight rollover in the corpus.** The
four the TTL branch rejects are rejected on Retention (26–50%, the static header
surviving — the easycall req-16 pattern from 001), not on gap.

Ticket 001's Decisions claim "the TTL branch tests both and runs first". It does
not: the `turn_context` diff is the first branch and TTL the second, so every
break carrying both a context difference and an expired prefix is claimed by the
context diff before TTL is ever tested. The doc and the code disagree — this
ticket makes the code right and the doc true.

## The second defect: fields that likely cannot be in the prompt

A `turn_context` carries 18 fields. A Cache Break can only be *explained* by a
field whose value actually reaches the prompt prefix. Today's diff includes
fields that look unlikely to — stated here as the hypothesis this ticket has to
confirm, not as a finding. **None of it is settled without the source; see
Evidence.**

- **Local bookkeeping** — `comp_hash`, `multi_agent_version`, `realtime_active`,
  `approvals_reviewer`. Nothing that reads as model-facing.
- **Apparent restatements** — `permission_profile` and
  `file_system_sandbox_policy` describe the same sandbox; `collaboration_mode`
  nests `model` and `reasoning_effort`, which are also top-level fields. One real
  change then fires 2–4 "fields changed", inflating both the diff and the
  explanation.

  `collaboration_mode` is the trap: its `settings` also carry
  `developer_instructions`, which is *not* a restatement of anything and is the
  likeliest genuinely prompt-bearing value in the record. It looks redundant and
  is not.

Observed shapes are consistent with this: `file_system_sandbox_policy+
permission_profile` (6 breaks), `approvals_reviewer+file_system_sandbox_policy+
permission_profile+workspace_roots` (7), `collaboration_mode` alone (11, only
128k Re-billed). Consistent with, not evidence for — co-occurrence shows two
fields move together, never that either reaches the prompt.

## Goal

A Cache Break is attributed to a `turn_context` change only when a
**Prefix-Bearing Field** changed, and only when a long Idle Gap does not already
explain the break. Everything else falls through to the cause that does explain
it.

## Vocabulary (add to `CONTEXT.md` before the code)

**Prefix-Bearing Field** — a `turn_context` field that can invalidate the cache
when it changes, either because its value is serialized into the prompt prefix
or because the provider's cache is keyed by it. The complement of today's
`TURN_CONTEXT_VOLATILE`, and a stronger idea: a field is *eligible* to explain a
break rather than merely non-volatile.

`model` is in on the second ground rather than the first — a cache entry belongs
to one model, so a swap invalidates it whether or not the name appears in the
prompt text. Every other candidate is in on the first ground, and that is a claim
about Codex's prompt assembly which this repo cannot observe (see Evidence).

## Scope

Two independent changes. **The ordering fix stands alone and needs no evidence
about prompt assembly** — ship it first, and treat the allow-list as a second
step that only lands once its fields are settled.

1. **Ordering.** Move the TTL branch ahead of the `turn_context` branch, so a
   resume is reported as a resume. Keep the `turn_context` branch reachable for
   real mid-Session config flips — those are the 27 breaks / 843k that no Idle
   Gap explains, and they are the actionable ones (*you changed approval mode
   mid-Session and it cost you*). On its own this moves all 32 mis-attributed
   breaks, which is the bulk of the correction.

2. **Allow-list.** Replace the `TURN_CONTEXT_VOLATILE` deny-list predicate
   *inside `turn_context_fingerprint()`* with a prefix-bearing allow-list, so
   excluded fields are never fingerprinted and cannot surface in a diff at all.
   Comment each entry with why it is in.

   The field is `effort`, not `reasoning_effort` — `reasoning_effort` exists only
   nested inside `collaboration_mode.settings`, alongside `model` and
   `developer_instructions`. Which also means **`collaboration_mode` cannot be
   dismissed as merely redundant**: it carries `developer_instructions`, which is
   the one nested value most likely to be genuinely prompt-bearing. Excluding it
   wholesale risks hiding a real cause; see Evidence.

Whichever of the two ships, re-run the census and correct any number in `001`,
`CONTEXT.md` or `README.md` that it moves.

## Evidence: what may settle whether a field is prefix-bearing

Whether a field reaches the prompt is a claim about Codex's prompt construction.
The rollout never records the assembled prompt, so **only direct evidence from
Codex's prompt-assembly source settles it.** Nothing in this repo can.

Explicitly *not* evidence:

- **Correlation with the Idle Gap.** "This field only ever changes alongside a
  long gap" says nothing about whether it is in the prompt — a genuinely
  prompt-bearing field could easily happen to change only on resumes. Reasoning
  from it would be the same time-confounded inference `011` exists to avoid.
- **Presence in `turn_context`.** The record is Codex's per-Turn local
  bookkeeping. Being in it is not being in the prompt.
- **`parse_codex.py`'s own comparison.** The fingerprint diff shows that a value
  changed, never that the model saw it. Using our output to justify our
  allow-list is circular.

**Default when evidence is unavailable: the field stays in.** Excluding a field
that really is prefix-bearing suppresses a true cause and pushes the break to
*unknown* — worse than today's over-claiming, which change 1 already fixes on its
own. Silence is the more expensive error here.

Unresolved until sourced, and not to be guessed: `current_date`,
`sandbox_policy` / `file_system_sandbox_policy` / `permission_profile`, and
`collaboration_mode`. These are the three groups carrying tokens; if the source
is not reachable this session, ship change 1, record that here, and leave the
allow-list unshipped rather than inferring membership.

## Acceptance

For change 1 (ordering), unconditionally:

- No break whose Idle Gap and Retention satisfy the TTL test is reported as
  `turn_context change`. The 16 `current_date`-only cold resumes read as
  *TTL expiry*.
- The 27 breaks with a genuine mid-Session config change and no long gap still
  read as `turn_context change`.
- Corrected corpus figures are recorded in Decisions. Expected direction:
  TTL expiry ≈ 64% of Re-billed (16.6M), `turn_context change` ≈ 3.3% (843k).
- Tests at the agreed `explain_breaks()` seam: a synthetic rollout with a
  long-gap cold resume whose `current_date` moved (→ TTL expiry), and one with
  a mid-Turn sandbox flip at a short gap (→ turn_context change).

For change 2 (allow-list), only if the Evidence section was satisfied:

- Every field in the allow-list cites its source in Decisions. Any field left
  unsourced is still fingerprinted, and Decisions says which and why.
- A diff arising from one real change names it once rather than spelling it
  four ways across `permission_profile`, `file_system_sandbox_policy` and
  `sandbox_policy`.
- If `collaboration_mode` is excluded, Decisions shows that nested
  `developer_instructions` was checked and found unchanged across the breaks it
  currently explains — otherwise the exclusion is hiding a cause, not removing a
  duplicate.

## Decisions

**Change 1 shipped 2026-08-28; change 2 did not.** The ordering fix needs no claim
about Codex's prompt assembly, so it ships alone exactly as Scope proposed. The
allow-list stays unshipped: the Evidence section admits only Codex's prompt-assembly
source, that source was not read this session, and the stated default is that an
unsourced field stays in. Nothing about `current_date`, the sandbox trio or
`collaboration_mode` was inferred from the corpus.

**The correction landed where it was predicted to.** Census over the same basis as
the Context table (392 Sessions, 475 Cache Breaks, 25.8M Re-billed, subagents
included):

| Break Cause | breaks | re-billed | share | was |
|---|---:|---:|---:|---:|
| TTL expiry | 155 | 16.60M | 64.3% | 49.6% |
| mid-turn history change | 194 | 3.06M | 11.8% | 11.8% |
| turn-boundary history rewrite | 56 | 2.49M | 9.6% | 9.6% |
| unknown | 35 | 2.10M | 8.1% | 8.1% |
| turn_context change | 27 | 0.84M | 3.3% | 18.0% |
| cache warm-up | 8 | 0.74M | 2.9% | 2.9% |

Exactly the 32 predicted breaks moved, all of them from `turn_context change` to
`TTL expiry`; no other cause changed by a single break. The two predicted figures
— TTL ≈ 64% / 16.6M and `turn_context change` ≈ 3.3% / 843k — came out at 64.3% /
16.60M and 3.3% / 843,349.

**Zero breaks now satisfy the TTL test and still report as `turn_context change`**,
checked across the whole corpus rather than only on the fixture.

**Four `current_date`-only breaks survive as `turn_context change`, by design.** Of
the 20, 16 moved; the remaining four are rejected by TTL on Retention (50%, 36%,
27%, 26% — the static header surviving, the easycall req-16 pattern from 001), not
on gap, so the reorder cannot reach them. They read as *the date is different*
today, which is unsatisfying and is precisely what change 2 exists to settle. They
carry 129k Re-billed between them: real, but not what was buying the correction.

**`CONTEXT.md` gained the precedence, not just the code.** "No Idle Gap accounts
for it" is now part of what `turn_context change` *means*, so the ordering is a
vocabulary fact rather than an implementation detail a later refactor could quietly
reverse. Ticket `001`'s claim that "the TTL branch tests both and runs first" needed
no edit — the code now says what the doc always did.

**No number moved in `README.md` or `001`.** README's `--explain` sample is
illustrative and still accurate; 001's mid-Turn percentages rest on
*mid-turn history change* and *unknown*, neither of which changed. `idle_gap_advice()`
does not go through `explain_breaks()`, so its ladder is untouched.

**Tests at the `explain_breaks()` seam, one driving and one guarding.** The driving
test is a cold two-day resume whose `current_date` moved — red before the reorder
with `'turn_context change' != 'TTL expiry'`. The guard is the discriminator the
reorder turns on: a day-long gap with a sandbox flip but 40% Retention still reads
as `turn_context change`, because TTL needs a cold cache as well as a long gap.
That guard passed without new code; it is there so a future simplification to
"long gap wins" fails loudly, and it is the fixture form of the four survivors
above.
