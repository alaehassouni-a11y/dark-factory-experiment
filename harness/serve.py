#!/usr/bin/env python3
"""Start the service for a validation run, against stub providers, or fail loudly.

    python harness/serve.py --port 8123

What it does, in order:

  1. Starts `harness/stubs.py` in-process on a free port: an OpenAI-shaped model and a
     Brave-shaped search. No secrets, no network. The gate proves the pipeline.
  2. Points the service at the stubs and at `harness/fixtures/wiki` through the same
     environment variables production uses, so nothing in the service knows it is being
     tested.
  3. Writes the stub port to `harness/.run/stub-port-<service port>` so `e2e.py` can ask
     the stubs how many times each provider was called. Keyed by the service's port
     because two of these run at once in the validate-pr workflow (the gate's own, and
     the one the E2E reviewer drives): a single shared file would hand the gate the
     reviewer's stub, whose call counts the reviewer is changing mid-assertion.
  4. Runs uvicorn as a child that DIES WITH THIS PROCESS. On Windows that is a Job Object
     with kill-on-close; on POSIX a SIGTERM handler. Without it, `appproc.py` terminating
     this script would orphan uvicorn, which would keep the port and poison the next lap.

The service refuses to import without OPENROUTER_API_KEY, and this script refuses to start
it without `uv` on PATH. Both refusals are named, because a step that cannot run has to be
loud, not absent (`3fc03a0`).
"""
from __future__ import annotations

import argparse
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    args = ap.parse_args()

    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    if not shutil.which(uv) and not Path(uv).exists():
        print("APP_START_REFUSED missing=uv - install uv (https://docs.astral.sh/uv/) so the "
              "service runs under app/backend/.venv", file=sys.stderr, flush=True)
        return 1

    stub_port = _free_port()
    stubs = serve_stubs(stub_port)
    RUN_DIR.mkdir(exist_ok=True)
    (RUN_DIR / f"stub-port-{args.port}").write_text(str(stub_port), encoding="utf-8")
    print(f"STUBS_STARTED port={stub_port}", flush=True)

    env = dict(os.environ)
    env.update({
        "OPENROUTER_API_KEY": "harness-stub-key",
        "OPENROUTER_BASE_URL": f"http://127.0.0.1:{stub_port}/v1",
        "BRAVE_SEARCH_API_KEY": "harness-stub-key",
        "WEB_SEARCH_BASE_URL": f"http://127.0.0.1:{stub_port}",
        "WIKI_RESOURCES_DIR": str(HERE / "fixtures" / "wiki"),
    })
    env.pop("VIRTUAL_ENV", None)

    proc = subprocess.Popen(
        [uv, "--project", "backend", "run", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=APP_DIR, env=env,
    )
    _bind_child_to_this_process(proc)
    try:
        return proc.wait()
    finally:
        if proc.poll() is None:
            proc.terminate()
        stubs.shutdown()


if __name__ == "__main__":
    sys.exit(main())
