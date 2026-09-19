#!/usr/bin/env python3
"""Start the service for a validation run, against stub providers, or fail loudly.

    python harness/serve.py --port 8123 [--web perplexity|brave]

What it does, in order:

  1. Starts `harness/stubs.py` in-process on a free port: an OpenAI-shaped model (chat,
     embeddings and the non-streamed research completion) and a Brave-shaped search. No
     secrets, no network. The gate proves the pipeline.
  2. Copies `harness/fixtures/wiki` into `harness/.run/wiki-<service port>` and points
     the service there with a one-second poll, so the journey can add and remove a
     document - the product's "indexed within seconds, no deploy" property - without
     touching a tracked file, and two laps cannot share a folder.
  3. Sets EVERY variable `app/backend/config.py` reads, explicitly. Not an override of
     the five that matter: a value left to the developer's shell or to `app/.env`
     configures the service under test, and a red gate then has a cause no rung names.
     `--web` chooses the fallback under test - `perplexity` (the production default,
     Sonar through OpenRouter) or `brave` (the alternative, and what the developer
     console uses) - and the chosen one is printed, so a mismatch is visible at step 1.
  4. Writes `harness/.run/run-<service port>.json` (the stub port, the chosen provider,
     the wiki folder, the log) so `e2e.py` can ask the stubs how many times each provider
     was called and write into the wiki. Keyed by the service's port because two of these
     run at once in the validate-pr workflow (the gate's own, and the one the E2E
     reviewer drives): a single shared file would hand the gate the reviewer's stub,
     whose call counts the reviewer is changing mid-assertion.
  5. Runs uvicorn as a child that DIES WITH THIS PROCESS. On Windows that is a Job Object
     with kill-on-close; on POSIX a SIGTERM handler. Without it, `appproc.py` terminating
     this script would orphan uvicorn, which would keep the port and poison the next lap.
     Its output goes to `harness/.run/service-<port>.log`, not to a pipe: `appproc.py`
     starts this script with a pipe it only reads after the process exits, and on Windows
     a child blocks once 4 KiB have gone unread - a deadlock the gate reports as an
     unrelated timeout. A file cannot fill, and the path is printed so a failure has
     somewhere to point.

The service refuses to import without OPENROUTER_API_KEY, and this script refuses to start
it without `uv` on PATH. Both refusals are named, because a step that cannot run has to be
loud, not absent (`3fc03a0`).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
APP_DIR = ROOT / "app"
RUN_DIR = HERE / ".run"

sys.path.insert(0, str(HERE))
from stubs import serve as serve_stubs  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _bind_child_to_this_process(proc: subprocess.Popen) -> None:
    """Make the child die when this process does, on either platform."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        job = kernel32.CreateJobObjectW(None, None)
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

        class _BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BasicLimits),
                        ("IoInfo", _IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        JobObjectExtendedLimitInformation = 9
        kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                         ctypes.byref(info), ctypes.sizeof(info))
        handle = kernel32.OpenProcess(0x1F0FFF, False, proc.pid)
        kernel32.AssignProcessToJobObject(job, handle)
        # The job handle must stay open for the lifetime of this process; leak it on purpose.
        globals()["_JOB_HANDLE"] = job
    else:
        def _forward(signum: int, _frame: object) -> None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _forward)
        signal.signal(signal.SIGINT, _forward)


def _run_wiki(port: int) -> Path:
    """A private copy of the fixture wiki, per run: the journey adds and removes a
    document in it and tracked files must not move."""
    target = RUN_DIR / f"wiki-{port}"
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(HERE / "fixtures" / "wiki", target)
    return target


def _service_env(stub_port: int, wiki_dir: Path, web: str) -> dict[str, str]:
    """Every variable app/backend/config.py reads, pinned. Anything left unset would be
    answered by the developer's shell or by app/.env, which is how a run passes or fails
    for a reason no test names."""
    env = dict(os.environ)
    env.update({
        # inference: the stub speaks OpenRouter's shapes, and nothing else is reachable
        "OPENROUTER_API_KEY": "harness-stub-key",
        "OPENROUTER_BASE_URL": f"http://127.0.0.1:{stub_port}/v1",
        "CHAT_MODEL": "anthropic/claude-sonnet-4.6",  # config.py's default, said out loud
        # the wiki: a per-run copy, watched fast enough for the journey to see it move
        "WIKI_RESOURCES_DIR": str(wiki_dir),
        "WIKI_POLL_SECONDS": "1",
        # the web fallback: exactly one of the two, chosen here rather than inherited
        "WEB_SEARCH_PROVIDER": web,
        "BRAVE_SEARCH_API_KEY": "harness-stub-key" if web == "brave" else "",
        "WEB_SEARCH_BASE_URL": f"http://127.0.0.1:{stub_port}",
        # serving: the journey drives the API directly; no browser origin is allowed
        "CORS_ORIGINS": "",
    })
    env.pop("VIRTUAL_ENV", None)
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--web", choices=("perplexity", "brave"), default="perplexity",
                    help="the web fallback under test; perplexity is production's default")
    args = ap.parse_args()

    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    if not shutil.which(uv) and not Path(uv).exists():
        print("APP_START_REFUSED missing=uv - install uv (https://docs.astral.sh/uv/) so the "
              "service runs under app/backend/.venv", file=sys.stderr, flush=True)
        return 1

    stub_port = _free_port()
    stubs = serve_stubs(stub_port)
    RUN_DIR.mkdir(exist_ok=True)
    wiki_dir = _run_wiki(args.port)
    log_path = RUN_DIR / f"service-{args.port}.log"
    # Kept for anything that still reads it; run-<port>.json is what e2e.py reads.
    (RUN_DIR / f"stub-port-{args.port}").write_text(str(stub_port), encoding="utf-8")
    (RUN_DIR / f"run-{args.port}.json").write_text(
        json.dumps({
            "stub_port": stub_port,
            "web_search": args.web,
            "wiki_dir": str(wiki_dir),
            "log": str(log_path),
        }),
        encoding="utf-8",
    )
    print(f"STUBS_STARTED port={stub_port} web_search={args.web} log={log_path}", flush=True)

    env = _service_env(stub_port, wiki_dir, args.web)

    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            [uv, "--project", "backend", "run", "uvicorn", "backend.main:app",
             "--host", "127.0.0.1", "--port", str(args.port)],
            cwd=APP_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        _bind_child_to_this_process(proc)
        try:
            rc = proc.wait()
        finally:
            if proc.poll() is None:
                proc.terminate()
            stubs.shutdown()

    if rc != 0:
        # The tail only, and only on failure: this process's own stdout IS a pipe that
        # appproc.py reads after the fact, and a long dump would be the bug item 10 names.
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
        print(f"APP_EXITED rc={rc} log={log_path}\n{tail}", file=sys.stderr, flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
