# The wiki

Every `.md` and `.txt` file in this folder (and its subfolders) is the Virtual Agent's
knowledge. The service reads them at startup, splits them into passages, and answers
client questions from them first, in whichever of the four supported languages the client
used. Only when nothing here covers a question does the agent search the web.

Adding a file here is the only way the wiki grows. There is no upload form and no editor,
on purpose: the folder is the authoring surface, and a change to it is a commit someone
can review.

Writing tips:

- One topic per file, with a `#` heading naming it. The heading is what the agent cites.
- Short paragraphs. A passage is a few paragraphs under one heading.
- Write in any of the four languages; the agent answers in the client's language.
- This README is not indexed.

The harness never reads this folder. It runs against its own fixture wiki under
`harness/fixtures/wiki/`, so what you put here changes what clients hear, not what the
gate checks.
