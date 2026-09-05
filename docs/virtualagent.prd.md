# Virtual Agent - Product Requirements

> **Provenance, stated plainly.** This document was written on 2026-09-03 from the
> four sentences in [`requirements.md`](../requirements.md), quoted in full below, and
> **before any code existed**. Everything in it is either a restatement of those
> sentences or a product value the factory chose in their absence; the second kind is
> marked and recorded in `.factory/decisions.md` so it can be overturned by a human
> without archaeology.
>
> From here on the order is the normal one: this file changes first, `MISSION.md`
> changes with it, in the same commit.
>
> Deliberately excluded: the stack, the architecture, the data model, the file layout.
> Those are engineering decisions, they are settled in this codebase, and a PRD that
> contains them is a spec nobody can change.

**Status:** live · **Owner:** human only · **Mission compressed from this:** `MISSION.md`

---

## The requirement, verbatim

> I need a virtual agent able to perform text to speech live to be able to ask
> questions to clients, and answer questions from clients live.
> The agent will be called from a mobile app available in ios.
> The agent will adapt to the client's detected language. Supported languages are:
> french, english, german and arabic.
> the agent will have access to a wiki, created from the virtualagent/resources folder
> and if the answer is not found, will default to results from the web.

Every sentence below traces to one of those four. Where it does not, it says so.

## The problem

Clients call with questions. The answers already exist, in a folder of documents the
business maintains, but nobody can read them a question at a time, in four languages,
at the moment the client asks. The client either waits for a person or gives up.

A search box is the wrong shape for this: the client is on a phone, may be speaking
rather than typing, and does not know which document the answer is in. What they need
is to be **asked and answered, out loud, in their own language**, by something that has
read the folder.

## Who it is for

Clients of the business, on an iPhone, who want to:

- ask a question in French, English, German or Arabic and hear the answer spoken back
  in the same language, without choosing a language first
- be asked the questions the agent needs answered to help them, out loud
- get an answer grounded in the business's own documents, and a web-sourced answer
  when the documents do not cover it

The Virtual Agent is **not** an operator tool. The person who maintains the wiki does
so by putting files in a folder, not through the product. Nobody logs in to manage
anything.

## The hypothesis, and what would falsify it

**Hypothesis:** a spoken answer in the client's own language, grounded in the
business's wiki, resolves most client questions without a person.

**What would falsify it:** clients abandoning sessions before the answer is spoken, or
most answers coming from the web rather than the wiki. If the wiki rarely has the
answer, the product is a worse web search with a voice; if clients do not wait for the
voice, the speech is decoration and a text reply would do.

That is why every answer declares where it came from, why the wiki is always consulted
first, and why the web path is visible in the transcript rather than blended in. The
declared source is the product.

## Scope for this version

**Live voice conversation.** The agent speaks every turn aloud as it is produced, not
after it is complete. The agent asks questions as well as answering them: it opens the
session by asking how it can help, asks the client to clarify when a question is
ambiguous, and asks the client to continue in a supported language when it cannot tell
which one they are using. The client speaks or types; both reach the same agent.

**Language adaptation.** The agent detects the client's language from what the client
says and answers in it. It follows the client if they switch mid-session. The supported
set is French, English, German and Arabic, and nothing else.

**Wiki knowledge.** The wiki is built from the `virtualagent/resources` folder in this
repository. Adding a document to that folder is how the wiki grows; there is no other
authoring surface. The agent answers from the wiki whenever the wiki covers the
question, and says which document it drew from.

**Web fallback.** When the wiki does not cover the question, the agent searches the web
and answers from what it finds, saying so and naming the pages. When neither the wiki
nor the web yields an answer, the agent says it does not know, in the client's language.
It never invents.

**iOS client.** A native iPhone app is the only client. It captures the client's voice,
speaks the agent's turns, shows the transcript, and needs no account to start.

## Non-goals

Sorted, because the sort is the part that matters once an agent is reading this.
**Never** means the factory rejects it forever, including the quarter it becomes
attractive.

**Never - additional surface area**
- A fifth language, or removal of one of the four. The set is a property, not a list.
- Any client other than the iOS app: Android, web, desktop, chat platforms, phone lines.
- A wiki authoring surface: upload forms, editors, an admin view. The folder is the
  authoring surface.
- More than one wiki, or per-client wikis. One folder, one deployment.
- Human hand-off: transferring the conversation to a person.

**Never - product category changes**
- Accounts, profiles, sign-in, or anything social.
- Payments, subscriptions, tiers.
- Answers with no declared source, or a "creative" mode that may invent.

**Never - stack substitution presented as a feature**
- Alternative or user-selectable inference providers, or local model support.

**Not yet, and therefore NOT in the mission's out-of-scope list** - these belong in the
backlog and the factory should not reject them on sight:
- Richer wiki formats beyond Markdown and plain text.
- Retrieval-quality work: chunking, ranking, prompt iteration, better confidence.
- Voice quality: nicer voices, barge-in, faster first sentence.
- Sessions that survive an app restart.

## Properties that cannot be edited

These are not features and no issue may argue them away. They are restated as hard
invariants in `MISSION.md` and as auto-reject triggers in `FACTORY_RULES.md`, because
the file read at reject time has to contain the rule.

1. **The supported languages are exactly French, English, German and Arabic.** From
   the requirement. Detection, prompts, speech and the client all follow that one set.
2. **The wiki is consulted before the web, and the web only when the wiki has no
   confident answer.** From the requirement. The order is not configurable.
3. **Every agent turn declares its source: wiki, web, or none.** A turn with source
   `none` is the agent saying it does not know. There is no fourth value. *Chosen by the
   factory* (D-001): the requirement says "if the answer is not found", which only
   works if not-found is a state the product can be in and admit to.
4. **A session is private to the client that opened it.** No other client, and no
   operator, can read or continue it. *Chosen by the factory* (D-002).
5. **A per-client daily turn cap.** It protects the inference budget, and a product
   whose cost scales with abuse is not a product. *Chosen by the factory* (D-003); the
   number lives in one module and only a human commit may change it.
6. **One inference provider.** *Chosen by the factory* (D-004).

## Success

- A client speaks a question and hears the answer in the same language. That is the
  whole funnel.
- Most answers come from the wiki, and every web answer is visibly a web answer.
- Adding a file to `virtualagent/resources` is all it takes for the agent to know
  something new.

## Open questions

Anything here is a `factory:needs-human`, never a guess:

- What the daily cap should be for a heavy but legitimate client.
- Whether typed input stays in the app once voice input is reliable, or is kept as the
  accessibility path.
- Whether the agent should ever ask the client to confirm the detected language before
  answering, or only when detection fails.
