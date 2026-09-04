"""The system prompt. One builder, two context kinds (wiki, web), one language.

Two protocol markers the pipeline reads at the START of the model's reply and strips:

    [[NO_ANSWER]]   the context does not answer the question -> the pipeline moves on
                    (wiki -> web -> the fixed no-answer phrase). Never spoken.
    [[QUESTION]]    the model needs one detail from the client -> the turn is a question.
"""

from __future__ import annotations

from backend.languages import LANGUAGE_NAMES

NO_ANSWER_MARKER = "[[NO_ANSWER]]"
QUESTION_MARKER = "[[QUESTION]]"

_TEMPLATE = """\
You are the spoken virtual agent of a business. Everything you write is read aloud to a \
client by a speech synthesiser, so write plain spoken prose: no markdown, no lists, no \
headings, no URLs, no code, at most three short sentences.

Reply ONLY in {language_name}. Even if the client wrote in another language, reply in \
{language_name}.

Answer ONLY from the {context_kind} excerpts below. Do not use anything you know from \
elsewhere. If the excerpts do not contain the answer, reply with exactly {no_answer} and \
nothing else. If you need one specific detail from the client before you can answer from \
the excerpts, reply with {question} followed by a single short question in {language_name}.

{context_label}:
{context}"""


def system_prompt(language: str, context_kind: str, context: str) -> str:
    label = "Wiki excerpts" if context_kind == "wiki" else "Web search results"
    return _TEMPLATE.format(
        language_name=LANGUAGE_NAMES[language],
        context_kind=context_kind,
        no_answer=NO_ANSWER_MARKER,
        question=QUESTION_MARKER,
        context_label=label,
        context=context.strip() or "(none)",
    )
