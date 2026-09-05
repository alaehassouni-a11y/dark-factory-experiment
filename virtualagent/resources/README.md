# The wiki

Every `.md` and `.txt` file in this folder (and its subfolders) is the Virtual Agent's
knowledge. The service reads them at startup and **watches the folder**: a file added,
edited or removed is re-indexed within seconds and the agent knows it on the next question.
No restart, no release. Only when nothing here covers a question does the agent search the
web, and it always says which it used.

In this repository this folder is the default wiki and the samples. In production the
service is pointed at a folder on the server (`WIKI_DIR` in the host `.env`) and this folder
is what the image carries when nothing is mounted over it. Either way, adding a file to the
folder is the only way the wiki grows: there is no upload form and no editor, on purpose.

## The knowledge format

One file per topic, Markdown, like this:

```markdown
# Opening hours

We are open from 9:00 to 18:00, Monday to Saturday. We are closed on Sunday and on public
holidays.

## Christmas

Between 24 December and 2 January we close at 16:00.
```

- **One `#` title, and it is the topic.** The title is what the agent cites as its source,
  so name the topic, not the file: "Returns policy", not "Notes".
- **Short paragraphs under `##` sections.** The service splits a file into passages by
  heading and paragraph and answers from the two or three that match best; a wall of text
  matches nothing well.
- **Plain facts, in spoken prose.** Everything the agent says is read aloud: no URLs, no
  bullet soup, numbers written the way one says them. "We deliver within two working days"
  is quotable; "our friendly team is at your service" is not.
- **Any of the four languages.** Write in the language the information exists in; the
  agent answers in the client's. A question in the document's own words matches most
  reliably, so keep the terms clients actually use.
- **This README is not indexed.** Neither is any file that is not `.md` or `.txt`.

## Importing existing documents

`tools/wiki/ingest.py` turns Word, PDF, PowerPoint, Excel, CSV, HTML, text and Markdown
files into this format, one file per topic, without touching the running service:

```bash
uv run --project tools/wiki python tools/wiki/ingest.py brochure.pdf hours.docx --out virtualagent/resources
```

Add `--dry-run` to see what it would write, `--force` to replace files that exist. Read
what it produced before trusting it: a converter preserves the words, not the judgement
about which of them a client needs.

The harness never reads this folder. It runs against its own fixture wiki under
`harness/fixtures/wiki/`, so what you put here changes what clients hear, not what the
gate checks.
