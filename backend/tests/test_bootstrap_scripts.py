from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


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

    run("bash", "scripts/stop-local.sh", "--quiet", cwd=tmp_path)

    assert not pid_file.exists()
