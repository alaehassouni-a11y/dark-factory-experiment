# Mission

**Derived from:** `docs/virtualagent.prd.md`
**Last reconciled with that PRD:** 2026-09-06

> This file is the PRD compressed to the part the factory has to obey. When the product
> changes, both files change in the same commit - otherwise the factory keeps faithfully
> building the old scope and nothing warns you. The PRD is a live document here, not a
> kickoff artifact.

## What the Virtual Agent Is

The Virtual Agent is a spoken assistant for a business's clients. A client opens the iOS app, speaks or types in French, English, German or Arabic, and the agent answers aloud in that language, live, from a wiki built out of a folder of documents (`virtualagent/resources` in this repository by default; a folder on the host in production, watched for changes). When the wiki does not cover the question the agent searches the web and says so. When neither does, it says it does not know. It also asks questions: how it can help, what the client meant, which supported language to continue in.

One wiki, one deployment, one iOS client.

## Who It's For

Clients of the business, on an iPhone, who want to:
- Ask a question out loud in their own language and hear the answer spoken back
- Be asked what the agent needs to know, out loud, rather than fill in a form
- Get answers grounded in the business's own documents, with the web as a declared fallback

The Virtual Agent is not an operator tool, a general-purpose assistant, a chat platform, or a multi-tenant service. Whoever maintains the wiki does so by putting files in a folder.

## Core Capabilities (In Scope)

**Live voice conversation**
- Every agent turn is spoken as it is produced, sentence by sentence, not after it completes
- The agent opens each session by asking how it can help
- The agent asks a clarifying question when the client's question is ambiguous
- The agent asks the client to continue in a supported language when it cannot detect one
- The client can speak or type; both reach the same agent

**Language adaptation**
- The agent detects the client's language from what the client says, with no language picker required
- The agent answers, and asks, in the detected language, and follows the client if they switch
- Supported languages: French, English, German, Arabic (see Hard Invariants)

**Wiki knowledge**
- The wiki is built from every Markdown and plain-text file in the wiki folder: `virtualagent/resources` in this repository by default, a folder on the host in production
- The service watches the folder and re-indexes when a file is added, changed or removed; a wiki change is not a deploy
- The agent answers from the wiki whenever the wiki covers the question and names the document it drew from
- Adding a file to the folder is the only authoring path; `tools/wiki` converts other document formats into files for it

**Web fallback**
- When the wiki has no confident answer the agent searches the web, answers from the results, and names the pages
- When neither the wiki nor the web yields an answer, the agent says it does not know, in the client's language
- The agent never invents an answer

**iOS client**
- A native iPhone app that captures the client's voice, speaks the agent's turns live, shows the transcript, and needs no account

## Out of Scope (Factory Must Never Build)

The factory is forbidden from accepting issues that expand the product in any of these directions. Issues asking for these things must be rejected at triage.

**Languages**
- A fifth language, a dialect variant presented as a language, or removal of one of the four

**Clients and channels**
- Android, web, desktop, or chat-platform clients
- Telephony, SMS, e-mail, or any channel other than the iOS app
- A public API, webhooks, or third-party clients

**Wiki**
- An upload form, editor, or admin view for the wiki
- More than one wiki, per-client wikis, or wiki content sourced from anywhere but the folder

**Conversation**
- Human hand-off or transfer to a live person
- A mode that answers without a source, or that may invent
- Accounts, profiles, sign-in, or anything social

**Monetization**
- Payments, subscriptions, tiers, paywalls

**Inference stack**
- Swapping the inference provider away from OpenRouter, adding user-selectable providers, or local models

## Hard Invariants (Not Tunable by Factory Issues)

These are not features. They are constraints that define what the Virtual Agent is. The factory is explicitly forbidden from modifying them even if an issue asks nicely, explains a good reason, or claims it's a bug.

1. **The supported languages are exactly French, English, German and Arabic.** Detection, prompts, speech voices and the client all follow one definition of that set. Any issue adding, removing or aliasing a language must be rejected at triage.

2. **The wiki is consulted before the web, and the web only when the wiki has no confident answer.** The order is not configurable and the web path may not be taken while the wiki has a confident answer.

3. **Every agent turn declares its source: `wiki`, `web`, or `none`.** `none` means the agent said it does not know. An answer with no source, or a fourth source value, is an auto-reject.

4. **A session is private to the client that opened it.** Every read or turn on a session carries that session's token. No other client and no operator can read or continue a session.

5. **The daily turn cap is 100 turns per client per 24 hours.** This number protects the inference budget. Any issue requesting the cap be raised, lowered, removed, made configurable, or bypassed for specific clients must be rejected at triage as a security concern. Only a human commit can change this value.

6. **OpenRouter is the only inference provider.** No provider swaps, no alternatives, no local models.

7. **The factory cannot modify governance files.** `MISSION.md`, `FACTORY_RULES.md`, and `CLAUDE.md` are the constitution. Any PR that touches them is an automatic reject.

## Allowed Evolutions

These are explicitly in scope and the factory can work on them when issues are filed:

- **Retrieval quality.** Chunking, ranking, the confidence decision between wiki and web, and prompt iteration are fair game as long as the wiki-before-web order and the declared source remain.
- **Voice quality.** Sentence segmentation, first-sentence latency, voice selection per language, and interruption handling in the app.
- **Detection quality.** Better language detection within the four supported languages.
- **Wiki formats.** Additional file formats under `virtualagent/resources`.
- **Transcript UX.** How the app shows the conversation, sources and the detected language.
- **Session durability.** Sessions that survive an app restart, as long as they remain private to their client.

## Quality Standards (Definition of Done)

Every change the factory ships must clear all three gates. A PR that skips any of these is not done.

**Gate 1 - Static checks pass**
- Type-check: zero errors
- Lint: zero warnings
- Format: clean
- Unit and integration tests: all pass

**Gate 2 - Usable without instructions**
- A first-time client can open the app, be greeted, speak, and hear an answer without reading anything
- No hidden gestures, no settings the client must find first, no "you have to know about this" affordances
- If something needs an explanation, the agent says it out loud

**Gate 3 - The end-to-end journey passes**
Every change - bug fix, feature, refactor, docs update that touches runnable code - must pass the journey in `FACTORY_RULES.md` §4, run by `python harness/ci.py`:

1. Start the service against the harness wiki and stub providers
2. Open a session and receive a spoken greeting with a voice locale
3. Ask a wiki-covered question in French and receive a French answer, spoken sentence by sentence, with source `wiki` and no web search made
4. Ask an uncovered question in German and receive a German answer with source `web` and named pages
5. Ask in Arabic and receive Arabic
6. Ask in an unsupported language and be asked, out loud, to continue in a supported one
7. Confirm that another session's token cannot read this session

It is not optional. A PR that skips it is not done, regardless of whether the change "seems unrelated" to the conversation flow.

## Non-Goals (Things the Virtual Agent Is Explicitly Not Trying To Be)

- A platform
- A multi-tenant SaaS
- A call-centre replacement with human escalation
- A general AI assistant
- A content management system
- A monetized product
- An Android or web app
- A developer tool with an API

The Virtual Agent is a focused spoken interface over one business's wiki, with the web as a declared fallback. Every feature decision should reinforce that focus. When in doubt, the answer is "that's out of scope."
