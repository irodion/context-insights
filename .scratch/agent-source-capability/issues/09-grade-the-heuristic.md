# 09 — Grade `explain_breaks()` against the first ground truth we have ever had

Type: research
Status: resolved
Blocked by: —

## Question

[02](02-claude-code-telemetry.md) found that Claude Code's server reports the
Break Cause (`message.diagnostics.cache_miss_reason`) and the Re-billed figure
(`cache_missed_input_tokens`). [06](06-agent-agnostic-contract.md) then asks
whether analysis should trust the source over our heuristic — but that is a
decision resting on a fact nobody has measured: **on the breaks where both
signals exist, how often does `explain_breaks()` already agree?**

This is the first external check this project has ever had. Every Break Cause
figure in `docs/tickets/001` and `010` — including the corrected census shipped
2026-08-28 — is unvalidated heuristic output. Measure the error rate.

**1. The confusion matrix.** Over Claude Code Sessions, run our arithmetic and
`explain_breaks()` logic and cross-tabulate our six Break Causes against the six
`cache_miss_reason` types, on the Requests where both exist. Report per-cause
agreement, and which of our causes is least reliable.

**2. Is the mapping actually one-to-one?** 02 called it "almost". Settle the
ambiguous cases with evidence rather than assertion: `messages_changed` was
mapped to *history rewrite* **or** *Compaction* — two of ours; `unavailable` was
mapped to *cache warm-up* on plausibility alone. Where a server type spans two of
our causes, say what separates them.

**3. Grade ticket 010's reorder directly.** The reorder made a long Idle Gap with
a cold cache outrank a `turn_context` diff. The server distinguishes exactly
these: `previous_message_not_found` (expiry) versus the four `*_changed` types
(config). **Does the server ever report a `*_changed` where our logic says TTL
expiry, or the reverse?** Each such case is a counter-example to a change already
shipped. Report them individually, not just as a rate.

**4. The non-overlapping populations.** 92 arithmetic breaks carry no server
reason and 72 server reasons carry no arithmetic break. For the second group: are
those Requests we classify as *hits*? If the server says the cache missed and we
say it did not, `BREAK_RATIO = 0.8` may be mis-set — check whether their
Retention clusters near the threshold.

**5. Does the verdict transfer to Codex?** Codex has no ground truth, so its
numbers inherit whatever error rate is measured here. Which of our six causes is
least reliable, and what share of Codex's corrected census (155 TTL expiry / 27
turn_context change / 194 mid-turn history change / 56 rewrite / 35 unknown / 8
warm-up) sits in it? State plainly how much confidence the Codex figures should
carry.

## Why this blocks 06

If the heuristic agrees with the server nearly always, the case for breaking the
agent-agnostic rule is weak — the server signal buys precision at compaction and
little else. If it disagrees often, the rule has been hiding real errors and the
case is strong. **06 cannot be decided honestly without this number.**

A finding that our heuristic is largely right is just as valuable as one that it
is wrong, and must not be argued away.

## Answer

Resolved 2026-08-28. 564 files / 95,219 records / 0 unparseable, guard session
excluded, all matching structural. `analyze()` and `explain_breaks()`
re-implemented from current source with branch order preserved. 226 main Sessions
/ 17,008 Requests → **130 Cache Breaks**, all 130 carrying a server reason — the
graded set is the *complete* main-session break population, not a sample.

**Headline: 70.8% agreement by count, 81.6% weighted by Re-billed Tokens.**
The heuristic is **right about how much and wrong about why.**

**1. Confusion matrix — per-cause agreement:**

| our cause | n | agree | rate |
|---|---:|---:|---:|
| TTL expiry | 94 | 89 | **94.7%** |
| turn_context change | 5 | 2 | 40.0% |
| cache warm-up | 0 | – | never fires in 17,008 Requests |
| turn-boundary history rewrite | 8 | 1 | 12.5% |
| mid-turn history change | 11 | 0 | **0.0%** |
| unknown | 12 | 0 | **0.0%** |

All 23 of the `mid-turn history change` / `unknown` cases were server-reported
config changes (19 `tools_changed`, 2 `model_changed`, 2 expiry). **Our "unknown"
bucket is not noise — it is a real cause we cannot see.** Robust: rebuilding the
fingerprint from any subset of {model, effort, cwd, gitBranch, permissionMode,
version} gives 70.8% every time.

**2. The mapping is NOT one-to-one, and [02](02-claude-code-telemetry.md)'s table
has a wrong row.** `unavailable` is **not** cache warm-up: 45 of its 47 main
occurrences sit on Requests we call **hits** with median Retention **1.0000**, and
none carries `cache_missed_input_tokens`. It means *"the reason is unavailable"*.
`messages_changed` genuinely spans Compaction and history rewrite, and
`COMPACTION_RATIO = 0.6` separates them cleanly (clusters at 0.157–0.381 and
1.072, nothing between). Only **2 of 29** `*_changed` Breaks reached our
`turn_context change` — nothing in a Claude Code transcript states the tool set,
so all 19 `tools_changed` are invisible to the fingerprint.

**3. Ticket 010's reorder — 5 counter-examples, and the reorder still wins.**
Of the 94 Requests the TTL branch claimed, **17 also had a context diff** — the
exact contested set the reorder was written to decide. The server confirms expiry
on **12** and a config change on **5**: right 70.6% of the time on its own
territory. Re-running the pre-010 branch order over the same 130 Breaks scores
**85/130 (65.4%)** against today's **92/130 (70.8%)**. **The change shipped this
morning is +7 Requests / +5.4pp.** The five counter-examples (gaps 7m–36m, all
with a real `model`/`permissionMode` diff) are the known price, not a refutation.

The larger error is next door: 9 Breaks where the server says expiry and we say
something else, 8 of them at gaps of 1h 52m–4.4 days with Retention **0.26–0.54**
— just above `COLD_RETENTION`. Cause is structural: a Claude Code Break retains a
**constant ~21k prefix block** (cached clusters at 21k on 94/130, matching the
Session's own first-Request `cache_read` within ±10% on 88/120). A *total* expiry
therefore shows Retention ≈ 21k/expected, not 0, so `COLD_RETENTION = 0.25`
misfires on every Session under ~85k of context. Floor-adjusted scores **74.6%**
(fitted here — a lead, not a result).

**4. `BREAK_RATIO = 0.8` is vindicated.** 61 Requests carry a server reason while
we call them hits; **none is within 0.05 of the threshold** (min Retention
0.9264, median 1.0000, median shortfall **2 tokens**). Nothing below 0.92 would
change. But 21 **Compactions** carry a reason, and 12 of those are Session resumes
after 7h–7.2 days that our Compaction branch books at **`rebilled = 0`** —
genuine expiries costed as free. Where the server gives a figure at a Compaction
it matches `input − cached` (1.08–1.15 on 8 of 9) while our `expected − cached`
over-counts **5.0–13.8x**.

**5. Transfer to Codex — trust the arithmetic, not the labels.**

**65.7% of Codex's corrected census (312/475) sits in causes measured below 50%
agreement; 60.0% (285/475) in causes below 20%.** Transferring per-cause rates
predicts ~35% of Codex cause labels would survive a server check.

- **Trust the counts and totals.** Break detection had **zero false positives**
  (130/130 confirmed), with 0.12 of threshold headroom.
- **Trust "TTL expiry".** 94.7% correct, and it carries 85.1% of Re-billed
  Tokens. The claim the tool exists to make — *long idle gaps are what cost you*
  — is validated by an independent source for the first time.
- **Do not trust the fine-grained causes.** `mid-turn history change`, `unknown`
  and `turn-boundary history rewrite` are 285 of 475 Codex Breaks and were wrong
  on every graded case.

**Coverage limit that constrains 06:** the server signal is effectively
main-session-only. **80 of 82 subagent Breaks carry no reason**, and subagents are
**38.7% (82/212) of all Breaks** in this corpus.

**And a third option for 06:** 16 of the 19 `tools_changed` Requests are
immediately preceded by a tool result carrying `total_deferred_tools` / `matches`
/ `query` — a deferred-tool load. **The cause is in the log, just not in anything
`explain_breaks()` reads.** That is fixable *inside* the agent-agnostic rule.

### Verdict for 06

Do not decide 06 as a single yes/no. The server signal buys **almost nothing on
volume** (81.6% token-weighted, and silent on 38.7% of Breaks) but **a great deal
on attribution** (0/19 on `tools_changed`), and is strictly better at Compaction.
Adopting the source signal for the *cause* while keeping our arithmetic as the
*measure* fits the evidence better than either extreme.
