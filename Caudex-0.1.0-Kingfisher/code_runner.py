from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

MAX_OUTPUT = 30_000
MAX_SOURCE = 100_000
MAX_STDIN = 20_000

# This is a classroom-development guardrail, not a real sandbox. The README
# intentionally explains that public deployment should use an isolated runner.
BLOCKED_PATTERNS = [
    (r"\b(system|popen|fork|vfork|exec[lvpe]*|CreateProcess|ShellExecute)\s*\(", "OS process execution is disabled in the local classroom runner."),
    (r"#\s*include\s*[<\"](?:filesystem|fstream|unistd\.h|sys/socket\.h|winsock2\.h|windows\.h)[>\"]", "File-system, socket, and OS headers are disabled in the local classroom runner."),
    (r"\b(remove|rename|unlink|rmdir|chmod|chown)\s*\(", "File-system modification calls are disabled in the local classroom runner."),
]


def _trim(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + "\n\n[output truncated by Caudex]"


def _guard_source(source: str) -> str | None:
    for pattern, message in BLOCKED_PATTERNS:
        if re.search(pattern, source, flags=re.IGNORECASE):
            return message
    return None


def _posix_limits():
    if os.name != "posix":
        return None

    def apply_limits():
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
            resource.setrlimit(resource.RLIMIT_FSIZE, (5_000_000, 5_000_000))
            # 256 MiB address-space ceiling. Some platforms may ignore it.
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
        except Exception:
            pass

    return apply_limits


def _runner_mode() -> str:
    return (os.getenv("CAUDEX_RUNNER_BACKEND") or "local").strip().lower()


def run_cpp(source: str, stdin_text: str = "") -> dict[str, Any]:
    source = (source or "")[:MAX_SOURCE]
    stdin_text = (stdin_text or "")[:MAX_STDIN]
    backend = _runner_mode()

    if backend == "disabled":
        return {
            "ok": False,
            "status": "runner_disabled",
            "stdout": "",
            "stderr": "The compiler is disabled. Set CAUDEX_RUNNER_BACKEND=local for trusted local development.",
            "duration_ms": 0,
        }

    if backend != "local":
        return {
            "ok": False,
            "status": "runner_not_configured",
            "stdout": "",
            "stderr": f"Runner backend '{backend}' is not implemented in this local prototype. Use an isolated Judge0/Docker runner before public deployment.",
            "duration_ms": 0,
        }

    compiler = os.getenv("CXX", "g++")
    compiler_path = shutil.which(compiler)
    if not compiler_path:
        return {
            "ok": False,
            "status": "compiler_missing",
            "stdout": "",
            "stderr": f"Cannot find '{compiler}'. Install g++/MinGW-w64 and make sure it is on PATH.",
            "duration_ms": 0,
        }

    blocked = _guard_source(source)
    if blocked:
        return {
            "ok": False,
            "status": "blocked_source",
            "stdout": "",
            "stderr": blocked,
            "duration_ms": 0,
        }

    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="caudex_") as tmp:
        tmpdir = Path(tmp)
        source_file = tmpdir / "main.cpp"
        exe_file = tmpdir / ("program.exe" if platform.system() == "Windows" else "program")
        source_file.write_text(source, encoding="utf-8")

        compile_cmd = [
            compiler_path,
            "-std=c++17",
            "-O0",
            "-pipe",
            "-Wall",
            "-Wextra",
            str(source_file),
            "-o",
            str(exe_file),
        ]
        try:
            compiled = subprocess.run(
                compile_cmd,
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=12,
                preexec_fn=_posix_limits(),
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": "compile_timeout",
                "stdout": "",
                "stderr": "Compilation exceeded the 12-second limit.",
                "duration_ms": round((time.perf_counter() - start) * 1000),
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "runner_error",
                "stdout": "",
                "stderr": f"Compiler could not start: {exc}",
                "duration_ms": round((time.perf_counter() - start) * 1000),
            }

        if compiled.returncode != 0:
            return {
                "ok": False,
                "status": "compile_error",
                "stdout": _trim(compiled.stdout or ""),
                "stderr": _trim(compiled.stderr or "Compilation failed."),
                "duration_ms": round((time.perf_counter() - start) * 1000),
            }

        try:
            ran = subprocess.run(
                [str(exe_file)],
                cwd=tmp,
                input=stdin_text,
                text=True,
                capture_output=True,
                timeout=4,
                preexec_fn=_posix_limits(),
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": "timeout",
                "stdout": "",
                "stderr": "Program exceeded the 4-second execution limit.",
                "duration_ms": round((time.perf_counter() - start) * 1000),
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "runtime_error",
                "stdout": "",
                "stderr": f"Program could not start: {exc}",
                "duration_ms": round((time.perf_counter() - start) * 1000),
            }

        return {
            "ok": ran.returncode == 0,
            "status": "success" if ran.returncode == 0 else "runtime_error",
            "stdout": _trim(ran.stdout or ""),
            "stderr": _trim(ran.stderr or ""),
            "exit_code": ran.returncode,
            "duration_ms": round((time.perf_counter() - start) * 1000),
        }
