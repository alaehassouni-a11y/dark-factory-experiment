#!/usr/bin/env python3
"""What can be checked of the iOS app without a Swift toolchain. Honest about its limits.

    uv run python harness/static_ios.py      (from app/backend, so pyyaml is importable)

Asserts: the XcodeGen spec parses and declares the VirtualAgent iOS target with the two
usage descriptions the app needs to listen and speak; the Info.plist parses; every Swift
file is non-empty with balanced braces and parentheses. That last one catches a truncated
file, not a type error. A compile happens on a Mac, in Xcode, by a person - FACTORY.md
names that gap.
"""
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
IOS = ROOT / "app" / "ios"

REQUIRED_KEYS = ("NSMicrophoneUsageDescription", "NSSpeechRecognitionUsageDescription")


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
    for path in swift:
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ROOT).as_posix()
        expect(f"{rel} is not empty", bool(text.strip()))
        expect(f"{rel} has balanced braces and parentheses",
               text.count("{") == text.count("}") and text.count("(") == text.count(")"),
               f"braces {text.count('{')}/{text.count('}')} parens {text.count('(')}/{text.count(')')}")

    if failures:
        for f in failures:
            print(f"  IOS_FAIL  {f}", flush=True)
        print(f"IOS_MANIFESTS_FAILED checks={checks} failures={len(failures)}", flush=True)
        return 1
    print(f"IOS_MANIFESTS_OK checks={checks} swift_files={len(swift)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
