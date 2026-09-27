"""Custos C++ runner abstraction.

Production recommendation: use a Judge0-compatible isolated runner by setting
CODE_RUNNER_BACKEND=judge0 and JUDGE0_URL. Local g++ execution is intentionally
opt-in (CODE_RUNNER_BACKEND=local and CODE_RUNNER_ALLOW_LOCAL=1) because a
normal Flask container is not a strong sandbox for untrusted code.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class RunResult:
    ok: bool
    status: str
    stdout: str = ""
    stderr: str = ""
    compile_output: str = ""
    runtime_ms: Optional[int] = None

    def to_dict(self):
        return asdict(self)


def backend_name() -> str:
    return os.getenv("CODE_RUNNER_BACKEND", "disabled").strip().lower() or "disabled"


def runner_status() -> dict:
    backend = backend_name()
    if backend == "judge0":
        return {
            "backend": "judge0",
            "ready": bool(os.getenv("JUDGE0_URL", "").strip()),
            "detail": "Judge0-compatible isolated runner",
        }
    if backend == "local":
        allowed = os.getenv("CODE_RUNNER_ALLOW_LOCAL", "0") == "1"
        compiler = shutil.which(os.getenv("CXX", "g++"))
        return {
            "backend": "local",
            "ready": bool(allowed and compiler),
            "detail": "Development-only local g++ runner",
        }
    return {
        "backend": "disabled",
        "ready": False,
        "detail": "Configure CODE_RUNNER_BACKEND before executing code",
    }


def _truncate(value: str, limit: int = 20000) -> str:
    value = value or ""
    return value if len(value) <= limit else value[:limit] + "\n[output truncated]"


def _run_judge0(source: str, stdin_text: str) -> RunResult:
    import requests

    base = os.getenv("JUDGE0_URL", "").rstrip("/")
    if not base:
        return RunResult(False, "runner_unavailable", stderr="JUDGE0_URL is not configured.")
    language_id = int(os.getenv("JUDGE0_CPP_LANGUAGE_ID", "54"))
    timeout = float(os.getenv("CODE_RUNNER_HTTP_TIMEOUT", "15"))
    headers = {"Content-Type": "application/json"}
    token = os.getenv("JUDGE0_TOKEN", "").strip()
    if token:
        headers[os.getenv("JUDGE0_AUTH_HEADER", "X-Auth-Token")] = token
    payload = {
        "source_code": source,
        "language_id": language_id,
        "stdin": stdin_text or "",
        "cpu_time_limit": float(os.getenv("CODE_RUNNER_CPU_SECONDS", "2")),
        "wall_time_limit": float(os.getenv("CODE_RUNNER_WALL_SECONDS", "5")),
        "memory_limit": int(os.getenv("CODE_RUNNER_MEMORY_KB", "131072")),
    }
    started = time.perf_counter()
    response = requests.post(
        f"{base}/submissions?base64_encoded=false&wait=true",
        headers=headers,
        data=json.dumps(payload),
        timeout=timeout,
    )
    elapsed = int((time.perf_counter() - started) * 1000)
    response.raise_for_status()
    data = response.json()
    status = (data.get("status") or {}).get("description", "Unknown")
    compile_output = _truncate(data.get("compile_output") or "")
    stderr = _truncate(data.get("stderr") or "")
    stdout = _truncate(data.get("stdout") or "")
    accepted = str(status).lower() == "accepted"
    runtime_ms = elapsed
    try:
        if data.get("time") is not None:
            runtime_ms = int(float(data["time"]) * 1000)
    except Exception:
        pass
    return RunResult(accepted, status, stdout, stderr, compile_output, runtime_ms)


def _local_preexec():
    # Best-effort Unix resource limits. This is NOT equivalent to container or
    # VM isolation and is therefore development-only.
    try:
        import resource
        cpu = int(float(os.getenv("CODE_RUNNER_CPU_SECONDS", "2")))
        memory = int(os.getenv("CODE_RUNNER_MEMORY_BYTES", str(128 * 1024 * 1024)))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (8, 8))
    except Exception:
        pass


def _run_local(source: str, stdin_text: str) -> RunResult:
    if os.getenv("CODE_RUNNER_ALLOW_LOCAL", "0") != "1":
        return RunResult(False, "runner_unavailable", stderr="Local execution is disabled. Set CODE_RUNNER_ALLOW_LOCAL=1 only for development.")
    cxx = shutil.which(os.getenv("CXX", "g++"))
    if not cxx:
        return RunResult(False, "runner_unavailable", stderr="g++ was not found on this machine.")
    compile_timeout = float(os.getenv("CODE_RUNNER_COMPILE_SECONDS", "8"))
    run_timeout = float(os.getenv("CODE_RUNNER_WALL_SECONDS", "5"))
    with tempfile.TemporaryDirectory(prefix="custos_cpp_") as td:
        src = os.path.join(td, "main.cpp")
        exe = os.path.join(td, "program.exe" if os.name == "nt" else "program")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(source)
        try:
            cp = subprocess.run(
                [cxx, "-std=c++17", "-O2", "-pipe", src, "-o", exe],
                cwd=td,
                capture_output=True,
                text=True,
                timeout=compile_timeout,
            )
        except subprocess.TimeoutExpired:
            return RunResult(False, "Compilation timeout", compile_output="Compilation exceeded the configured time limit.")
        if cp.returncode != 0:
            return RunResult(False, "Compilation Error", compile_output=_truncate(cp.stderr or cp.stdout))
        started = time.perf_counter()
        try:
            kwargs = dict(
                args=[exe], cwd=td, input=stdin_text or "", capture_output=True,
                text=True, timeout=run_timeout,
            )
            if os.name != "nt":
                kwargs["preexec_fn"] = _local_preexec
            rp = subprocess.run(**kwargs)
        except subprocess.TimeoutExpired as exc:
            return RunResult(False, "Time Limit Exceeded", stdout=_truncate(exc.stdout or ""), stderr="Program exceeded the configured time limit.")
        runtime_ms = int((time.perf_counter() - started) * 1000)
        status = "Accepted" if rp.returncode == 0 else f"Runtime Error ({rp.returncode})"
        return RunResult(rp.returncode == 0, status, _truncate(rp.stdout), _truncate(rp.stderr), "", runtime_ms)


def run_cpp(source: str, stdin_text: str = "") -> RunResult:
    source = source or ""
    if not source.strip():
        return RunResult(False, "Empty Source", stderr="Write C++ code before running it.")
    if len(source) > int(os.getenv("CODE_RUNNER_MAX_SOURCE", "50000")):
        return RunResult(False, "Source Too Large", stderr="The source file exceeds the configured size limit.")
    if len(stdin_text or "") > int(os.getenv("CODE_RUNNER_MAX_STDIN", "10000")):
        return RunResult(False, "Input Too Large", stderr="Custom input exceeds the configured size limit.")
    backend = backend_name()
    try:
        if backend == "judge0":
            return _run_judge0(source, stdin_text)
        if backend == "local":
            return _run_local(source, stdin_text)
        return RunResult(False, "runner_unavailable", stderr="C++ execution is disabled. Configure CODE_RUNNER_BACKEND.")
    except Exception as exc:
        return RunResult(False, "Runner Error", stderr=f"Runner request failed: {exc}")


def normalized_output(value: str) -> str:
    return "\n".join(line.rstrip() for line in (value or "").strip().splitlines())


def grade_hidden_tests(source: str, tests: list[dict]) -> tuple[list[dict], int]:
    results = []
    passed = 0
    for index, test in enumerate(tests, start=1):
        result = run_cpp(source, str(test.get("stdin", "")))
        expected = normalized_output(str(test.get("expected", "")))
        actual = normalized_output(result.stdout)
        ok = result.ok and actual == expected
        if ok:
            passed += 1
        results.append({
            "index": index,
            "passed": ok,
            "status": result.status,
            "runtime_ms": result.runtime_ms,
            # Hidden expected/stdin values intentionally not returned to student UI.
        })
        if result.status in {"Compilation Error", "Compilation timeout", "Source Too Large", "runner_unavailable"}:
            # No value in repeatedly compiling the same failing source.
            break
    return results, passed
