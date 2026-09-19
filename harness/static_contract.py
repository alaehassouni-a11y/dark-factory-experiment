#!/usr/bin/env python3
"""THE TWO-CONSUMER CONTRACT, checked mechanically instead of by eye.

    python harness/static_contract.py

`docs/API.md` has two consumers - the service and an iOS app that has never been
compiled - and until now the only thing holding them together was a rule in
FACTORY_RULES.md that says they must travel together and a reviewer instruction that
says to read every changed Swift file slowly. A builder could rename a field on
`SentenceEvent`, update `docs/API.md` in the same PR, keep every backend test green
(they assert the service's own shape) and ship an app that throws `malformedEvent` on
the first spoken sentence. That is the shape of the 2026-04-15 incident.

WHAT IT COMPARES, and where each side comes from:

  * event names - `event: <name>` in the SSE block of `docs/API.md`, `_sse("<name>", ...)`
    in `app/backend/routes/sessions.py`, and `case "<name>":` in the decoder in
    `app/ios/VirtualAgent/AgentAPI.swift`. All three sets must be equal, and the unnamed
    token frame must be handled on both sides.
  * event fields - for each event, the keys the backend actually emits (read from the
    `to_dict` of the dataclass `encode()` maps that event to, in
    `app/backend/agent/events.py`) against the stored properties of the Swift struct the
    decoder hands that event to (`app/ios/VirtualAgent/Models.swift`), and against the
    sample payload in `docs/API.md`.
  * the same for the bodies: `POST /api/sessions`, `GET /api/sessions/{id}` and the 429
    error body.

WHAT IT ASSERTS, in both directions:

  1. every backend key is decoded by the app - a key the app never reads is a promise
     in API.md that nothing keeps;
  2. every NON-OPTIONAL Swift property is always emitted by the backend - a
     conditionally-emitted key behind a non-optional property is a decode failure of the
     whole turn, which is exactly how a live agent goes silent;
  3. every key documented in API.md exists in the backend, and every key the backend
     always emits is documented.

The Python side is read with `ast`, so a rename moves the check with it. The Swift and
Markdown sides are read with careful regexes, which is the honest limit of a stdlib check
against a language with no parser here: SO IT FAILS WHEN IT CANNOT FIND SOMETHING. A
struct that stopped matching, an `encode()` that stopped being an if-chain, a doc block
that moved - each of those is a CONTRACT_FAIL and not a silent pass, because a contract
check that quietly checks nothing is worse than none.

Emits `CONTRACT_OK events=N fields=N bodies=N`. Stdlib only.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
API_MD = ROOT / "docs" / "API.md"
EVENTS_PY = ROOT / "app" / "backend" / "agent" / "events.py"
SESSIONS_PY = ROOT / "app" / "backend" / "routes" / "sessions.py"
STORE_PY = ROOT / "app" / "backend" / "sessions" / "store.py"
MODELS_SWIFT = ROOT / "app" / "ios" / "VirtualAgent" / "Models.swift"
AGENTAPI_SWIFT = ROOT / "app" / "ios" / "VirtualAgent" / "AgentAPI.swift"

FAILURES: list[str] = []
COMPARED_FIELDS = 0


def fail(detail: str) -> None:
    FAILURES.append(detail)


# --------------------------------------------------------------------------- Python side


class Emitted:
    """What one `to_dict` puts on the wire.

    `always` is what every call emits; `sometimes` is what only one branch emits. The
    distinction is the whole of assertion 2: a non-optional Swift property standing in
    front of a `sometimes` key decodes fine in testing and throws in production.
    """

    def __init__(self, always: set[str], sometimes: set[str]) -> None:
        self.always = always
        self.sometimes = sometimes

    @property
    def all(self) -> set[str]:
        return self.always | self.sometimes


def _dict_keys(node: ast.AST) -> set[str] | None:
    if not isinstance(node, ast.Dict):
        return None
    keys: set[str] = set()
    for k in node.keys:
        if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
            return None
        keys.add(k.value)
    return keys


def _subscript_key(target: ast.AST) -> str | None:
    if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
        value = target.slice.value
        if isinstance(value, str):
            return value
    return None


def dataclass_fields(cls: ast.ClassDef) -> list[str]:
    return [s.target.id for s in cls.body
            if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]


def emitted_by(func: ast.FunctionDef, fields: list[str], where: str) -> Emitted | None:
    """Read one `to_dict`/`to_list` body. Understands the three shapes this repo uses."""
    ret = next((n for n in ast.walk(func) if isinstance(n, ast.Return) and n.value), None)
    if ret is None or ret.value is None:
        fail(f"{where}: no return statement to read the emitted keys from")
        return None

    always: set[str] | None = None
    value = ret.value

    # `return asdict(self)` -> every declared field.
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) \
            and value.func.id == "asdict":
        always = set(fields)
    # `return {...}`
    elif isinstance(value, ast.Dict):
        always = _dict_keys(value)
    # `d = {...}` ... `return d`
    elif isinstance(value, ast.Name):
        for stmt in func.body:
            targets = (stmt.targets if isinstance(stmt, ast.Assign)
                       else [stmt.target] if isinstance(stmt, ast.AnnAssign) else [])
            if any(isinstance(t, ast.Name) and t.id == value.id for t in targets):
                always = _dict_keys(stmt.value) if stmt.value is not None else None
    # `return [s.to_dict() for s in ...]` -> the element type is checked separately.
    elif isinstance(value, (ast.ListComp, ast.List)):
        return Emitted(set(), set())

    if always is None:
        fail(f"{where}: the return value is not a shape this checker understands "
             f"(asdict(self), a dict literal, or a dict built in one local variable). "
             f"Teach harness/static_contract.py the new shape rather than removing it")
        return None

    # A key assigned under an `if` is conditional; one assigned at the top level is not.
    conditional: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.If):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Assign):
                    for t in inner.targets:
                        key = _subscript_key(t)
                        if key:
                            conditional.add(key)
    for stmt in func.body:
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                key = _subscript_key(t)
                if key:
                    always.add(key)

    return Emitted(always - conditional, conditional)


def python_payloads(path: Path) -> dict[str, Emitted]:
    """class name -> what its `to_dict` emits, for every dataclass in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, Emitted] = {}
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        func = next((f for f in cls.body
                     if isinstance(f, ast.FunctionDef) and f.name in ("to_dict", "to_list")), None)
        if func is None:
            continue
        got = emitted_by(func, dataclass_fields(cls), f"{path.name}:{cls.name}.{func.name}")
        if got is not None:
            out[cls.name] = got
    return out


def encode_map(path: Path) -> dict[str, str]:
    """SSE event name -> the dataclass `encode()` maps it from. '' is the unnamed frame."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    func = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "encode"), None)
    if func is None:
        fail(f"{path.name}: no `encode()` - the one function that knows the wire format")
        return {}
    out: dict[str, str] = {}
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)
                and test.func.id == "isinstance" and len(test.args) == 2
                and isinstance(test.args[1], ast.Name)):
            continue
        cls = test.args[1].id
        call = next((n for n in ast.walk(node) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id == "_sse"), None)
        if call is None or not call.args:
            fail(f"{path.name}: the encode() branch for {cls} does not call _sse()")
            continue
        first = call.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            out[first.value] = cls
        elif isinstance(first, ast.Constant) and first.value is None:
            out[""] = cls
        else:
            fail(f"{path.name}: the encode() branch for {cls} names its event dynamically; "
                 f"the wire format has to be readable")
    return out


def returned_dict(path: Path, func_name: str) -> ast.Dict | None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    func = next((n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == func_name), None)
    if func is None:
        fail(f"{path.name}: no function {func_name}()")
        return None
    ret = next((n for n in ast.walk(func) if isinstance(n, ast.Return)
                and isinstance(n.value, ast.Dict)), None)
    if ret is None:
        fail(f"{path.name}:{func_name} no longer returns a dict literal; "
             f"harness/static_contract.py can no longer read the body it sends")
        return None
    assert isinstance(ret.value, ast.Dict)
    return ret.value


def nested_dict(node: ast.Dict, key: str) -> ast.Dict | None:
    for k, v in zip(node.keys, node.values):
        if isinstance(k, ast.Constant) and k.value == key and isinstance(v, ast.Dict):
            return v
    return None


def error_body_keys(path: Path) -> set[str] | None:
    """The 429 body: the one error payload that carries more than `detail`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "JSONResponse"):
            continue
        status = next((kw.value for kw in node.keywords if kw.arg == "status_code"), None)
        content = next((kw.value for kw in node.keywords if kw.arg == "content"), None)
        if isinstance(status, ast.Constant) and status.value == 429:
            keys = _dict_keys(content) if content is not None else None
            if keys is None:
                fail(f"{path.name}: the 429 body is not a dict literal any more")
            return keys
    fail(f"{path.name}: no JSONResponse(status_code=429, ...) - "
         f"MISSION hard invariant 5's body is gone or moved")
    return None


# ---------------------------------------------------------------------------- Swift side

STRUCT_RE = re.compile(r"\bstruct\s+(\w+)\s*(?::[^{\n]*)?\{")
PROPERTY_RE = re.compile(r"^\s*(?:public\s+|private\s+|internal\s+)?(?:var|let)\s+"
                         r"(\w+)\s*:\s*([^={\n]+?)\s*(?:=.*)?$")


def _body_after(text: str, open_brace: int) -> str:
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1:i]
    return ""


def swift_structs(path: Path) -> dict[str, dict[str, bool]]:
    """struct name -> {stored property name: is_optional}. Computed properties excluded."""
    text = path.read_text(encoding="utf-8")
    out: dict[str, dict[str, bool]] = {}
    for m in STRUCT_RE.finditer(text):
        body = _body_after(text, m.end() - 1)
        props: dict[str, bool] = {}
        depth = 0
        for line in body.splitlines():
            stripped = line.strip()
            if depth == 0:
                pm = PROPERTY_RE.match(line)
                if pm and not stripped.endswith("{"):
                    props[pm.group(1)] = pm.group(2).strip().endswith("?")
            depth += line.count("{") - line.count("}")
        out[m.group(1)] = props
    return out


DECODER_CASE_RE = re.compile(
    r'case\s+(nil|"(?P<name>\w+)")\s*:(?P<body>.*?)(?=\n\s*case\s|\n\s*default\s*:)',
    re.DOTALL)
DECODE_TYPE_RE = re.compile(r"decode\(\s*\[?\s*(\w+)\s*\]?\s*\.self")


def swift_event_types(path: Path) -> dict[str, str]:
    """SSE event name -> the Swift type the decoder hands it to. '' is the unnamed frame."""
    text = path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in DECODER_CASE_RE.finditer(text):
        name = m.group("name") or ""
        t = DECODE_TYPE_RE.search(m.group("body"))
        out[name] = t.group(1) if t else ""
    if not out:
        fail(f"{path.name}: found no `case \"<event>\":` branches in the event decoder - "
             f"either the decoder moved or this checker's regex no longer matches it")
    return out


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


# ------------------------------------------------------------------------- Markdown side


def md_event_samples(path: Path) -> dict[str, set[str]]:
    """SSE event name -> the keys of the sample payload documented beneath it."""
    text = path.read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^event:\s*(\w+)\s*$", line)
        if not m:
            continue
        data = next((ln for ln in lines[i + 1:i + 3] if ln.startswith("data:")), None)
        if data is None:
            fail(f"API.md: `event: {m.group(1)}` has no `data:` line under it")
            continue
        try:
            payload = json.loads(data[len("data:"):].strip())
        except json.JSONDecodeError as e:
            fail(f"API.md: the sample payload for `{m.group(1)}` is not valid JSON: {e}")
            continue
        if isinstance(payload, list):
            payload = payload[0] if payload and isinstance(payload[0], dict) else {}
        if not isinstance(payload, dict):
            fail(f"API.md: the sample payload for `{m.group(1)}` is not an object")
            continue
        out[m.group(1)] = set(payload.keys())
    return out


def md_json_block(path: Path, after: str, must_have: str) -> dict | None:
    """The first ```json block after a heading, e.g. the `POST /api/sessions` response."""
    text = path.read_text(encoding="utf-8")
    start = text.find(after)
    if start < 0:
        fail(f"API.md: no section {after!r}")
        return None
    for m in re.finditer(r"```json\n(.*?)\n```", text[start:], re.DOTALL):
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and must_have in payload:
            return payload
    fail(f"API.md: no ```json block carrying {must_have!r} under {after!r}")
    return None


# ------------------------------------------------------------------------ the comparison


def compare(label: str, backend: Emitted, swift: dict[str, bool],
            documented: set[str] | None) -> None:
    """The three assertions, for one payload."""
    global COMPARED_FIELDS
    decoded = {snake(p) for p in swift}
    COMPARED_FIELDS += len(backend.all) + len(swift)

    for key in sorted(backend.all - decoded):
        fail(f"{label}: the service emits {key!r} and the app decodes nothing by that name. "
             f"Add it to the Swift struct or stop sending it - API.md has two consumers")

    for prop, optional in sorted(swift.items()):
        key = snake(prop)
        if optional:
            continue
        if key not in backend.all:
            fail(f"{label}: the app requires {prop!r} (non-optional) and the service never "
                 f"emits {key!r}; every frame would fail to decode")
        elif key in backend.sometimes:
            fail(f"{label}: the app requires {prop!r} (non-optional) but the service emits "
                 f"{key!r} only on one branch; make the Swift property optional")

    if documented is None:
        return
    for key in sorted(documented - backend.all):
        fail(f"{label}: API.md documents {key!r} and the service never emits it")
    for key in sorted(backend.always - documented):
        fail(f"{label}: the service always emits {key!r} and API.md does not document it")


def main() -> int:  # noqa: C901
    for path in (API_MD, EVENTS_PY, SESSIONS_PY, STORE_PY, MODELS_SWIFT, AGENTAPI_SWIFT):
        if not path.is_file():
            fail(f"missing {path.relative_to(ROOT).as_posix()} - "
                 f"the contract has four definitions and one of them is gone")
    if FAILURES:
        for f in FAILURES:
            print(f"  CONTRACT_FAIL  {f}", flush=True)
        print(f"CONTRACT_FAILED failures={len(FAILURES)}", flush=True)
        return 1

    payloads = python_payloads(EVENTS_PY)
    encoded = encode_map(SESSIONS_PY)
    swift_types = swift_event_types(AGENTAPI_SWIFT)
    structs = swift_structs(MODELS_SWIFT)
    documented = md_event_samples(API_MD)

    # --- 1. the event names, three sources, one set ---------------------------
    backend_names = {n for n in encoded if n}
    app_names = {n for n in swift_types if n}
    doc_names = set(documented)
    if backend_names != app_names or backend_names != doc_names:
        fail(f"event names differ: routes/sessions.py={sorted(backend_names)} "
             f"AgentAPI.swift={sorted(app_names)} API.md={sorted(doc_names)}")
    if "" not in encoded:
        fail("routes/sessions.py no longer emits the unnamed token frame")
    if "" not in swift_types:
        fail("AgentAPI.swift's decoder has no `case nil:` for the unnamed token frame")

    # --- 2. the fields of every named event -----------------------------------
    for name in sorted(backend_names & app_names & doc_names):
        cls = encoded[name]
        emitted = payloads.get(cls)
        if emitted is None:
            fail(f"event {name!r}: no readable to_dict on {cls} in agent/events.py")
            continue
        # `sources` is a list of Source; the element type is what both sides shape.
        if not emitted.all and cls in payloads:
            element = payloads.get("Source")
            if element is None:
                fail(f"event {name!r}: {cls} emits a list and there is no Source.to_dict "
                     f"to read the element shape from")
                continue
            emitted = element
        swift_type = swift_types.get(name, "")
        struct = structs.get(swift_type)
        if not struct:
            fail(f"event {name!r}: the app decodes it as {swift_type or '<nothing>'}, which is "
                 f"not a struct with stored properties in Models.swift")
            continue
        compare(f"event {name!r}", emitted, struct, documented[name])

    # --- 3. the bodies --------------------------------------------------------
    bodies = 0

    created = returned_dict(SESSIONS_PY, "create_session")
    doc_created = md_json_block(API_MD, "### `POST /api/sessions`", "session_token")
    if created is not None and doc_created is not None:
        keys = _dict_keys(created) or set()
        compare("POST /api/sessions", Emitted(keys, set()),
                structs.get("CreateSessionResponse", {}), set(doc_created))
        bodies += 1
        greeting = nested_dict(created, "greeting")
        doc_greeting = doc_created.get("greeting")
        if greeting is None or not isinstance(doc_greeting, dict):
            fail("POST /api/sessions: the greeting object could not be read on both sides")
        else:
            compare("POST /api/sessions greeting", Emitted(_dict_keys(greeting) or set(), set()),
                    structs.get("Greeting", {}), set(doc_greeting))
            bodies += 1

    store = python_payloads(STORE_PY)
    doc_transcript = md_json_block(API_MD, "### `GET /api/sessions/{session_id}`", "turns")
    if "Session" in store and doc_transcript is not None:
        compare("GET /api/sessions/{id}", store["Session"],
                structs.get("SessionTranscript", {}), set(doc_transcript))
        bodies += 1
    else:
        fail("GET /api/sessions/{id}: no readable Session.to_dict in sessions/store.py")
    if "Turn" in store:
        turns = doc_transcript.get("turns") if isinstance(doc_transcript, dict) else None
        doc_turn: set[str] | None = None
        if isinstance(turns, list) and turns:
            # The documented turns differ by role; the union is what the app may meet.
            doc_turn = {k for t in turns if isinstance(t, dict) for k in t}
        compare("transcript turn", store["Turn"], structs.get("TranscriptTurn", {}), doc_turn)
        bodies += 1
    else:
        fail("transcript turn: no readable Turn.to_dict in sessions/store.py")

    err = error_body_keys(SESSIONS_PY)
    if err is not None:
        compare("429 body", Emitted(err, set()), structs.get("ErrorBody", {}), None)
        bodies += 1

    if FAILURES:
        for f in FAILURES:
            print(f"  CONTRACT_FAIL  {f}", flush=True)
        print(f"CONTRACT_FAILED failures={len(FAILURES)}", flush=True)
        return 1
    print(f"CONTRACT_OK events={len(backend_names)} fields={COMPARED_FIELDS} bodies={bodies}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
