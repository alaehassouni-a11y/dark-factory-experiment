#!/usr/bin/env python3
"""What can be checked of the iOS app without a Swift toolchain. Honest about its limits.

    uv run --all-extras python harness/static_ios.py   (from app/backend, so pyyaml imports)

Asserts: the XcodeGen spec parses and declares the VirtualAgent iOS target with the two
usage descriptions the app needs to listen and speak; the Info.plist parses; every Swift
file is non-empty with balanced braces and parentheses. That last one catches a truncated
file, not a type error. A compile happens on a Mac, in Xcode, by a person - FACTORY.md
names that gap.

AND THE FOUR-LANGUAGE RULE, which until now was a sentence in CLAUDE.md and an
instruction to a reviewer to read every changed Swift file slowly. `Phrases.swift` exists
so that everything the client sees or hears exists in all four supported languages; a
`Text("Retry")` anywhere else is an English string shown to a French, German or Arabic
client, and the gate stayed green for every one of them. So: no bare string literal may
be the first argument of a text-bearing SwiftUI initialiser outside `Phrases.swift`
(the product name is the one whitelisted exception - a name is not translated), and every
`case` of `enum Phrase` must reach a `pick` with four non-empty translations. Both are
counted, because a rule that silently stops applying is the shape of every bug this repo
has filed against its own gate.
"""
from __future__ import annotations

import plistlib
import re
import sys
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
IOS = ROOT / "app" / "ios"
PHRASES = IOS / "VirtualAgent" / "Phrases.swift"

REQUIRED_KEYS = ("NSMicrophoneUsageDescription", "NSSpeechRecognitionUsageDescription")

# The initialisers whose first argument is shown to, or spoken to, the client.
TEXT_BEARING = re.compile(
    r"(?:(?<![\w.])(?P<init>Text|Button|Label|Section|TextField|Toggle|Link)"
    r"|\.(?P<mod>navigationTitle|navigationBarTitle|accessibilityLabel|accessibilityHint"
    r"|accessibilityValue|confirmationDialog|alert))\s*\(")

COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)

# A name is not translated. This is the whole whitelist on purpose: every other entry
# would be a string somebody decided one language was enough for.
WHITELIST = {"Virtual Agent"}

LANGS = ("en", "fr", "de", "ar")


def strip_comments(text: str) -> str:
    """Blank out comments, keeping offsets, so a sentence in prose is not an offence."""
    return COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _scan_call(text: str, open_paren: int, stop_at_comma: bool) -> str:
    """Source inside the call whose `(` is at `open_paren`; the first argument, or all."""
    depth = 0
    i = open_paren
    start = open_paren + 1
    in_string = False
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        elif ch == "," and depth == 1 and stop_at_comma:
            return text[start:i]
        i += 1
    return text[start:]


def first_argument(text: str, open_paren: int) -> str:
    return _scan_call(text, open_paren, stop_at_comma=True)


def call_arguments(text: str, open_paren: int) -> str:
    return _scan_call(text, open_paren, stop_at_comma=False)


def swift_literals(src: str) -> list[tuple[int, str]]:
    """Every Swift string literal in `src`, as (offset, text), interpolation-aware.

    A regex cannot do this: `"Language: \\(name ?? "not detected yet")"` is ONE literal
    with another nested inside its interpolation, and a naive `"..."` match reads it as
    two half-strings and reports nonsense. Both are user-facing, so both come back - the
    outer with its interpolations collapsed to `\\(…)`.
    """
    out: list[tuple[int, str]] = []
    i, n = 0, len(src)
    while i < n:
        if src[i] != '"':
            i += 1
            continue
        start, i = i, i + 1
        parts: list[str] = []
        while i < n:
            ch = src[i]
            if ch == "\\" and i + 1 < n and src[i + 1] == "(":
                depth, j, in_string = 0, i + 1, False
                while j < n:
                    c = src[j]
                    if in_string:
                        if c == "\\":
                            j += 2
                            continue
                        if c == '"':
                            in_string = False
                    elif c == '"':
                        in_string = True
                    elif c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                out.extend((start, value) for _, value in swift_literals(src[i + 2:j]))
                parts.append("\\(…)")
                i = j + 1
                continue
            if ch == "\\" and i + 1 < n:
                parts.append(src[i:i + 2])
                i += 2
                continue
            if ch == '"':
                i += 1
                break
            parts.append(ch)
            i += 1
        out.append((start, "".join(parts)))
    return out


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def bare_literals(path: Path) -> list[str]:
    """Every user-facing string literal in this file that is not in Phrases.swift."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = strip_comments(raw)
    rel = path.relative_to(ROOT).as_posix()
    offences: list[str] = []
    for m in TEXT_BEARING.finditer(text):
        call = m.group("init") or m.group("mod")
        arg = first_argument(text, m.end() - 1)
        for _, value in swift_literals(arg):
            if not value.strip() or value in WHITELIST:
                continue
            offences.append(f"{rel}:{line_of(text, m.start())} {call}(\"{value}\")")
    return offences


def brace_body(text: str, open_brace: int) -> str:
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1:i]
    return ""


def phrase_cases() -> tuple[list[str], list[str]]:
    """(case names, complaints). Every case must reach four non-empty translations."""
    if not PHRASES.is_file():
        return [], [f"{PHRASES.relative_to(ROOT).as_posix()} does not exist - the four-language "
                    "rule has nowhere to live"]
    text = strip_comments(PHRASES.read_text(encoding="utf-8", errors="replace"))

    enum = re.search(r"\benum\s+Phrase\b[^{]*\{", text)
    if enum is None:
        return [], ["Phrases.swift: no `enum Phrase` - this checker can no longer read it"]
    body = brace_body(text, enum.end() - 1)

    # Case declarations are the `case` lines at the enum's own brace depth; anything
    # deeper belongs to a method's switch. Reading the whole body would count those too,
    # and cutting at the first `func` would miss a case declared after one.
    cases: list[str] = []
    depth = 0
    for line in body.splitlines():
        if depth == 0:
            m = re.match(r"^\s*case\s+(\w+)", line)
            if m:
                cases.append(m.group(1))
        depth += line.count("{") - line.count("}")
    if not cases:
        return [], ["Phrases.swift: `enum Phrase` declares no cases"]

    func = re.search(r"\bfunc\s+text\s*\(\s*in\b[^{]*\{", body)
    if func is None:
        return cases, ["Phrases.swift: no `func text(in language:)` to read the "
                       "translations out of"]
    arms_text = brace_body(body, func.end() - 1)

    marks = [(m.group(1), m.start()) for m in re.finditer(r"\bcase\s+\.(\w+)", arms_text)]
    arms: dict[str, str] = {}
    for i, (name, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(arms_text)
        arms[name] = arms_text[start:end]

    complaints: list[str] = []
    for name in cases:
        arm = arms.get(name)
        if arm is None:
            complaints.append(f"Phrase.{name}: no `case .{name}` arm in text(in:) - "
                              "the case exists and says nothing")
            continue
        pick = re.search(r"\bpick\s*\(", arm)
        if pick is None:
            complaints.append(f"Phrase.{name}: does not go through pick(lang, en:, fr:, "
                              "de:, ar:), so nothing guarantees four languages")
            continue
        args = call_arguments(arm, pick.end() - 1)
        literals = dict(swift_literals(args))
        missing: list[str] = []
        for lang in LANGS:
            label = re.search(rf"\b{lang}\s*:\s*", args)
            # The translation must be the literal that starts exactly at the label:
            # `en: someOtherString` is not a translation this file can vouch for.
            if label is None or not literals.get(label.end(), "").strip():
                missing.append(lang)
        if missing:
            complaints.append(f"Phrase.{name}: no non-empty translation for "
                              f"{', '.join(missing)}")
    return cases, complaints


def main() -> int:
    failures: list[str] = []
    checks = 0

    def expect(name: str, ok: bool, detail: str = "") -> None:
        nonlocal checks
        checks += 1
        if not ok:
            failures.append(f"{name}: {detail}")

    spec_path = IOS / "project.yml"
    expect("project.yml exists", spec_path.is_file(), str(spec_path))
    spec = {}
    if spec_path.is_file():
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    target = (spec.get("targets") or {}).get("VirtualAgent") or {}
    expect("the VirtualAgent target is an iOS application",
           target.get("type") == "application" and str(target.get("platform", "")).lower() == "ios",
           f"target={target}")
    expect("the target names an iOS deployment version",
           bool(target.get("deploymentTarget")), f"target={target}")

    plist_path = IOS / "VirtualAgent" / "Info.plist"
    expect("Info.plist exists", plist_path.is_file(), str(plist_path))
    plist: dict = {}
    if plist_path.is_file():
        try:
            plist = plistlib.loads(plist_path.read_bytes())
        except Exception as e:  # noqa: BLE001
            failures.append(f"Info.plist parses: {e}")
    for key in REQUIRED_KEYS:
        expect(f"Info.plist carries {key}", bool(plist.get(key)), "missing")

    swift = sorted(IOS.rglob("*.swift"))
    expect("there is at least one Swift source", bool(swift), str(IOS))
    offences: list[str] = []
    for path in swift:
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ROOT).as_posix()
        expect(f"{rel} is not empty", bool(text.strip()))
        expect(f"{rel} has balanced braces and parentheses",
               text.count("{") == text.count("}") and text.count("(") == text.count(")"),
               f"braces {text.count('{')}/{text.count('}')} parens {text.count('(')}/{text.count(')')}")
        if path.resolve() != PHRASES.resolve():
            offences.extend(bare_literals(path))

    expect("every user-facing string outside Phrases.swift goes through a Phrase",
           not offences,
           "these are shown or spoken in English to every client, whatever language they "
           "are speaking - move them into enum Phrase: " + "; ".join(offences))

    cases, complaints = phrase_cases()
    expect("every Phrase case supplies four non-empty translations",
           not complaints, "; ".join(complaints))

    if failures:
        for f in failures:
            print(f"  IOS_FAIL  {f}", flush=True)
        print(f"IOS_MANIFESTS_FAILED checks={checks} failures={len(failures)}", flush=True)
        return 1
    print(f"PHRASES_OK cases={len(cases)}", flush=True)
    print(f"IOS_MANIFESTS_OK checks={checks} swift_files={len(swift)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
