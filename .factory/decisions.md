# Decisions

Product values the factory chose on its own, and the questions it stopped to ask.

**How this file works.** `FACTORY_RULES.md` §7 splits values in two. A **product** value -
a phrase, a default, a top-k, a snippet length - the factory may choose, record here, and
carry on; the merge is held for a human but the work is not blocked. A **judgement**
value - a floor, a tolerance the journey asserts against, a required marker, a defect in
the mutation set, the cap - it may never choose, because choosing one is tuning the judge.

**Ask a given decision once.** A second issue that needs the same answer references the
ID and carries on. It does not re-ask. An earlier version of this rule told the plan node
to stop for "an answer to any open question", and a PRD that was honest about what it had
not settled blocked every issue downstream of it - four issues, four escalations, zero
PRs, and the same question asked four times. The more honest the spec, the less the
factory could do.

**Numbering restarted 2026-09-03.** The product was replaced that day; the three entries
recorded against DynaChat (an unset e2e floor, a journey defined in two places, three
mutations caught below the independence line) described code that no longer exists and
are in git history (`eaf804b`). The PRD cites D-001 through D-004 below by ID.

Append only. Newest at the bottom.

---

## D-001 · Not-found is a state the product admits to

**Status:** decided by the factory · **Raised:** 2026-09-03 · **Kind:** product

The requirement says "if the answer is not found, will default to results from the web".
That only works if not-found is a state the product can be in and say so. So every agent
turn declares a source from a closed set - `wiki`, `web`, or `none` - and `none` means
the agent said, out loud, that it does not know. There is no fourth value and no answer
without one.

Recorded in the PRD as property 3 and in `MISSION.md` as hard invariant 3. The phrasing
of the no-answer sentence in each language (`languages.py`) is a product value the
factory may change; the existence of the `none` state is not.

---

## D-002 · A session is private to the client that opened it

**Status:** decided by the factory · **Raised:** 2026-09-03 · **Kind:** product, with a
judgement edge

The requirement says nothing about privacy. The factory chose the strictest reading
compatible with "no accounts": a session is created anonymously, returns a token, and
every later read or turn carries it. No other client and no operator can read or continue
a session. Sessions expire after 24 hours in process.

Recorded as PRD property 4, MISSION hard invariant 4, and asserted by the holdout against
the assembled app. The 24-hour TTL is a product value; the token check itself is
protected code (`app/backend/auth.py`).

---

## D-003 · A per-client daily turn cap, and the number is 100

**Status:** cap chosen by the factory, number confirmed by the human commit that set
MISSION.md · **Raised:** 2026-09-03 · **Kind:** judgement

A product whose cost scales with abuse is not a product. The factory chose a per-client
cap counted on the `client_id` the app generates once and keeps. The **number** is a
judgement value: it lives in one module (`app/backend/rate_limit.py`), the holdout
asserts it is defined nowhere else, and only a human commit may change it. 100 per 24
hours is what MISSION.md pins today.

**Open under this ID:** what the cap should be for a heavy but legitimate client. The PRD
lists it as an open question. An issue that needs that answer references D-003 and is
`factory:needs-human`; it does not re-ask.

---

## D-004 · One inference provider

**Status:** decided by the factory · **Raised:** 2026-09-03 · **Kind:** product, then
frozen

OpenRouter, for both chat completions and the embeddings that index the wiki. The
requirement did not say; the factory chose one provider so that the cost, the model and
the failure modes are one thing to reason about, and MISSION.md then froze it as hard
invariant 6. The chat model may be canaried through `CHAT_MODEL` on the inactive colour;
the provider may not change.

---

## D-005 · The app is verified by a person

**Status:** open, deferred by the owner 2026-09-05 · **Raised:** 2026-09-04 · **Blocks:** nothing
today; every app issue eventually

**2026-09-05:** the owner chose to keep work on the desktop for now: no Mac, no macOS CI
runner, no simulator. The service is developed and tested from a PC through the API and
the harness; the app stays in the repo as written. When this is picked up again, the
cheapest path is a GitHub Actions `macos-latest` workflow that runs `xcodegen generate`,
builds for the simulator and runs `VirtualAgentTests`; the voice half stays a device check.

The iOS app was written on a machine with no Xcode, no XcodeGen and no iOS SDK. It has
never been generated, compiled, or run, and its unit tests have never executed
(`app/ios/README.md`, "Not verified"). The factory's machines have no Swift toolchain
either. `harness/static_ios.py` checks the manifests and that every Swift file has
balanced braces, and says plainly that this is not a compile.

So the half of the product a client touches is outside the gate. The gate proves the
contract the app is written against; whether the app honours it, whether the voice is
intelligible, whether the first sentence arrives fast enough to feel live, are things a
person with a Mac and an iPhone establishes.

**Recommendation:** generate the project once on a Mac, fix the first build, run the
XCTest target, drive one session end to end on a device, and record what was seen in
this entry. Until then, issues against the app are accepted (a compile error is a bug
with a reproduction) but the validator cannot confirm a fix; the PR body carries a
"Manual verification" section a human runs.

---

## D-006 · The mutation runner cannot use the journey

**Status:** open · **Raised:** 2026-09-04 · **Blocks:** nothing today

`harness/mutations/run.py` runs `ci.py --quick` plus the holdout per defect, not the
full gate: it mutates in place, and a live service holding the port across eight defects
is a runner nobody would trust. So a defect that only the journey (`e2e.py`) could catch
would escape the mutation set. Today all eight are caught by static, unit or holdout, so
the gap has not cost anything; it is still a gap.

The same gap from the other side: the holdout has no liveness scenario, so
`sentences-only-at-the-end` is the one defect of eight caught below the independence
line (`MUTATIONS_ABOVE_LINE=7`, measured 2026-09-04).

**Recommendation:** add a holdout scenario that asserts a `SentenceEvent` arrives before
the last token, and when a defect is added that only a live process can reveal (an SSE
framing regression), extend the runner to start the service per defect rather than
pretend `--quick` covers it. Both are judgement changes and human commits.

---

## D-007 · The real wiki has one document

**Status:** open · **Raised:** 2026-09-04 · **Blocks:** the PRD's falsification test

`virtualagent/resources/` holds `about-the-virtual-agent.md` and nothing else. The
business's documents - the ones the requirement calls "a wiki" - are not in the folder.
Every client question that is not about the agent itself will go to the web, which is
exactly the state the PRD says would falsify the product ("most answers coming from the
web rather than the wiki").

This is not a code defect and the factory cannot fix it: the folder is the authoring
surface and only the business knows what belongs in it. **Recommendation:** the human
adds the documents, in whichever of the four languages they exist, one topic per file
with a `#` heading. A merge to `main` is a deploy.
