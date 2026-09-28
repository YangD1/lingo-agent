#!/usr/bin/env python3
"""Claude Code hooks for lingo-agent.

Usage: lingo_hooks.py <session-start|pre-compact|stop|pre-tool|post-tool>
Reads the hook payload (JSON) from stdin, writes hook output (JSON) to stdout.
Every hook fails open: an unexpected error must never block the session.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
PROGRESS = ROOT / "docs" / "PROGRESS.md"
SESSION_LOG = ROOT / "docs" / "SESSION_LOG.md"
STATE_DIR = ROOT / ".claude" / "state"  # gitignored
SNAPSHOT = STATE_DIR / "precompact-snapshot.md"

# Paths whose changes do not count as "code changed" for the Stop check.
NON_CODE_PREFIXES = ("docs/", ".claude/", "CLAUDE.md", "README.md", "LICENSE", ".gitignore", ".env.example")

SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),  # Anthropic
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{32,}"),  # OpenAI / DeepSeek style
    re.compile(r"lsv2_[a-z]{2}_[A-Za-z0-9_]{20,}"),  # LangSmith
    re.compile(r"gsk_[A-Za-z0-9]{32,}"),  # Groq
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),  # Google
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return ""


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def latest_log_entry() -> str:
    if not SESSION_LOG.exists():
        return "(docs/SESSION_LOG.md 不存在)"
    text = SESSION_LOG.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## ", text)
    return ("## " + parts[1]).strip() if len(parts) > 1 else "(暂无交接记录)"


def current_stage() -> str:
    if not PROGRESS.exists():
        return ""
    lines = PROGRESS.read_text(encoding="utf-8").splitlines()
    return "\n".join(ln for ln in lines if ln.startswith(("**当前阶段**", "**阻塞项**")))


def session_start(payload: dict) -> None:
    source = payload.get("source", "startup")
    status = git("status", "--short", "--branch").strip() or "(clean)"
    stage = current_stage()
    parts = [
        "【lingo-agent 会话上下文（SessionStart 钩子自动注入）】",
        stage,
        "git status:\n" + status,
        "最新交接记录:\n" + latest_log_entry(),
    ]
    if source == "compact":
        parts.insert(
            1,
            "⚠️ 上下文刚刚被压缩。先确认 docs/PROGRESS.md 和 docs/SESSION_LOG.md 已经记录了压缩前的进展；"
            "如果没有，立即补写交接记录，再继续工作。",
        )
        if SNAPSHOT.exists():
            parts.append("压缩前快照:\n" + SNAPSHOT.read_text(encoding="utf-8"))
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "\n\n".join(p for p in parts if p),
            }
        }
    )


def pre_compact(payload: dict) -> None:
    # PreCompact cannot make the model write anything before compaction, so the
    # hook itself snapshots the work state; SessionStart(source=compact) re-injects it.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        f"时间: {datetime.now():%Y-%m-%d %H:%M:%S}（trigger={payload.get('trigger', '?')}）\n\n"
        f"git status:\n{git('status', '--short') or '(clean)'}\n"
        f"git diff --stat:\n{git('diff', '--stat') or '(none)'}\n",
        encoding="utf-8",
    )
    emit({"systemMessage": "lingo-agent: 已保存压缩前快照（.claude/state/precompact-snapshot.md）"})


def changed_code_mtime() -> float:
    newest = 0.0
    for line in git("status", "--porcelain", "-uall").splitlines():
        path = line[3:].split(" -> ")[-1].strip('"')
        if not path or path.startswith(NON_CODE_PREFIXES):
            continue
        f = ROOT / path
        if f.exists():
            newest = max(newest, f.stat().st_mtime)
    return newest


def stop(payload: dict) -> None:
    if payload.get("stop_hook_active"):
        return  # loop guard: already blocked once this turn
    code_mtime = changed_code_mtime()
    if not code_mtime:
        return
    docs_mtime = max((p.stat().st_mtime for p in (PROGRESS, SESSION_LOG) if p.exists()), default=0.0)
    if docs_mtime >= code_mtime:
        return
    emit(
        {
            "decision": "block",
            "reason": (
                "代码有改动，但 docs/PROGRESS.md 和 docs/SESSION_LOG.md 都比最新的代码改动旧。"
                "按 CLAUDE.md 会话协议：更新 PROGRESS.md 的任务状态；如果要结束本次会话或切换任务，"
                "再在 SESSION_LOG.md 顶部写交接记录。更新完再结束。"
            ),
        }
    )


def deny(reason: str) -> None:
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def find_secret(text: str) -> str | None:
    for pat in SECRET_PATTERNS:
        if m := pat.search(text or ""):
            return m.group(0)[:12] + "…"
    return None


def pre_tool(payload: dict) -> None:
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input", {}) or {}

    if tool == "Bash":
        cmd = ti.get("command", "")
        if re.search(r"\bgit\s+commit\b", cmd):
            staged = git("diff", "--cached", "-U0")
            if hit := find_secret(staged):
                deny(f"暂存区疑似包含密钥（{hit}）。开源仓库禁止提交密钥：把它移到 .env，再重新暂存。")
            staged_files = git("diff", "--cached", "--name-only").split()
            if bad := [f for f in staged_files if re.match(r"(.*/)?\.env(\..+)?$", f) and not f.endswith(".env.example")]:
                deny(f"禁止提交 env 文件: {', '.join(bad)}")
        return

    path = ti.get("file_path") or ti.get("notebook_path") or ""
    name = Path(path).name
    if re.fullmatch(r"\.env(\..+)?", name) and name != ".env.example":
        deny(f"禁止 Claude 写入 {name}。密钥由用户手动维护；需要新增变量时，改 .env.example 并告诉用户。")
        return
    content = ti.get("content") or ti.get("new_string") or ti.get("new_source") or ""
    for edit in ti.get("edits", []) or []:
        content += "\n" + (edit.get("new_string") or "")
    if hit := find_secret(content):
        deny(f"写入内容疑似包含密钥（{hit}）。改为从环境变量读取。")


def ruff_cmd() -> list[str] | None:
    venv_ruff = ROOT / "backend" / ".venv" / "bin" / "ruff"
    if venv_ruff.exists():
        return [str(venv_ruff)]
    if shutil.which("ruff"):
        return ["ruff"]
    if shutil.which("uvx"):
        return ["uvx", "ruff"]
    return None


def post_tool(payload: dict) -> None:
    ti = payload.get("tool_input", {}) or {}
    path = ti.get("file_path") or (payload.get("tool_response") or {}).get("filePath") or ""
    if not path.endswith(".py") or not Path(path).exists():
        return
    if cmd := ruff_cmd():
        subprocess.run([*cmd, "format", "--quiet", path], cwd=ROOT, capture_output=True, timeout=60)


HANDLERS = {
    "session-start": session_start,
    "pre-compact": pre_compact,
    "stop": stop,
    "pre-tool": pre_tool,
    "post-tool": post_tool,
}

if __name__ == "__main__":
    try:
        raw = sys.stdin.read()
        HANDLERS[sys.argv[1]](json.loads(raw) if raw.strip() else {})
    except Exception as exc:  # fail open
        print(f"lingo_hooks error: {exc!r}", file=sys.stderr)
    sys.exit(0)
