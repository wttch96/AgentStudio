from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )


def test_bootstrap_archives_main_copies_env_and_switches_local_to_dev(tmp_path: Path):
    shutil.copy2(REPOSITORY / "bootstrap.sh", tmp_path / "bootstrap.sh")
    shutil.copy2(REPOSITORY / ".env.example", tmp_path / ".env.example")
    (tmp_path / "snapshot.txt").write_text("main snapshot\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\n.sandbox/\n", encoding="utf-8")

    run("git", "init", "-b", "main", cwd=tmp_path)
    run("git", "config", "user.name", "Bootstrap Test", cwd=tmp_path)
    run("git", "config", "user.email", "bootstrap@example.test", cwd=tmp_path)
    run("git", "add", ".", cwd=tmp_path)
    run("git", "commit", "-m", "main snapshot", cwd=tmp_path)

    # 本地开发修改不应进入 main 沙箱，但切换到 dev 后必须保留。
    (tmp_path / "snapshot.txt").write_text("local development change\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "BACKEND_PORT=5011\nFRONTEND_PORT=5184\n",
        encoding="utf-8",
    )

    run("bash", "bootstrap.sh", "setup", cwd=tmp_path)

    assert run("git", "branch", "--show-current", cwd=tmp_path).stdout.strip() == "dev"
    assert (tmp_path / "snapshot.txt").read_text(encoding="utf-8") == (
        "local development change\n"
    )
    assert (tmp_path / ".sandbox" / "snapshot.txt").read_text(encoding="utf-8") == (
        "main snapshot\n"
    )
    assert (tmp_path / ".sandbox" / ".env").read_text(encoding="utf-8") == (
        "BACKEND_PORT=5011\nFRONTEND_PORT=5184\n"
    )
    metadata = (tmp_path / ".sandbox" / ".bootstrap-meta").read_text(encoding="utf-8")
    assert "source_branch=main" in metadata
    assert f"source_commit={run('git', 'rev-parse', 'main', cwd=tmp_path).stdout.strip()}" in metadata


def test_stop_script_refuses_pid_that_is_not_current_project_service(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    run_dir = tmp_path / ".run"
    scripts_dir.mkdir()
    run_dir.mkdir()
    shutil.copy2(REPOSITORY / "scripts" / "stop-local.sh", scripts_dir / "stop-local.sh")
    pid_file = run_dir / "backend.pid"
    pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")
    (run_dir / "backend.started").write_text(
        "not the current process start time\n",
        encoding="utf-8",
    )

    result = run(
        "bash",
        "scripts/stop-local.sh",
        "--quiet",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 1
    assert "拒绝停止 backend" in result.stderr
    assert pid_file.is_file()
    os.kill(os.getpid(), 0)


def test_stop_script_removes_stale_pid_file(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    run_dir = tmp_path / ".run"
    scripts_dir.mkdir()
    run_dir.mkdir()
    shutil.copy2(REPOSITORY / "scripts" / "stop-local.sh", scripts_dir / "stop-local.sh")
    pid_file = run_dir / "frontend.pid"
    pid_file.write_text("99999999\n", encoding="utf-8")
    started_file = run_dir / "frontend.started"
    started_file.write_text("stale\n", encoding="utf-8")

    run("bash", "scripts/stop-local.sh", "--quiet", cwd=tmp_path)

    assert not pid_file.exists()
    assert not started_file.exists()


def test_start_script_follows_and_rotates_backend_log_by_default():
    script = (REPOSITORY / "scripts" / "start-local.sh").read_text(encoding="utf-8")

    assert 'BACKEND_LOG_FOLLOW="${BACKEND_LOG_FOLLOW:-1}"' in script
    assert 'tail -n "${BACKEND_LOG_LINES}" -F "${RUN_DIR}/backend.log"' in script
    assert 'rotate_log "${RUN_DIR}/backend.log"' in script
    assert 'kill "${LOG_TAIL_PID}"' in script


def test_stop_script_stops_matching_backend_process(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    run_dir = tmp_path / ".run"
    backend_dir = tmp_path / "backend"
    scripts_dir.mkdir()
    run_dir.mkdir()
    backend_dir.mkdir()
    shutil.copy2(REPOSITORY / "scripts" / "stop-local.sh", scripts_dir / "stop-local.sh")
    (backend_dir / "run.py").write_text(
        "import time\nwhile True:\n    time.sleep(1)\n",
        encoding="utf-8",
    )

    process = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=backend_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        (run_dir / "backend.pid").write_text(f"{process.pid}\n", encoding="utf-8")
        started = ""
        for _ in range(20):
            try:
                started = run(
                    "ps",
                    "-p",
                    str(process.pid),
                    "-o",
                    "lstart=",
                    cwd=tmp_path,
                ).stdout.strip()
            except PermissionError:
                pytest.skip("当前测试沙箱禁止调用 ps")
            if started:
                break
            time.sleep(0.05)
        assert started
        (run_dir / "backend.started").write_text(f"{started}\n", encoding="utf-8")

        result = run(
            "bash",
            "scripts/stop-local.sh",
            "--quiet",
            cwd=tmp_path,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        process.wait(timeout=3)
        assert not (run_dir / "backend.pid").exists()
        assert not (run_dir / "backend.started").exists()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)
