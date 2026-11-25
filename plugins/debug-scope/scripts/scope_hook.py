#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreToolUse(Read) 软提醒：问题未解决且已试 >=2 次时，提示读取范围外的文件。

只提醒，不拦截。项目里没有 .claude/scope-state.json 时完全静默。
"""

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def emit(msg: str) -> int:
    # ensure_ascii=True：纯 ASCII 输出，避免 Windows 控制台编码把中文弄乱
    print(json.dumps({
        "systemMessage": msg,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": msg,
        },
    }, ensure_ascii=True))
    return 0


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    if data.get("tool_name") != "Read":
        return 0

    cwd = Path(data.get("cwd") or ".")
    state_path = cwd / ".claude" / "scope-state.json"
    if not state_path.exists():
        return 0

    try:
        st = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    if st.get("mode", "warn") != "warn" or st.get("escalate"):
        return 0

    iss = st.get("issue") or {}
    tries = int(iss.get("tries") or 0)
    if iss.get("state") != "open" or tries < 2:
        return 0

    fp = (data.get("tool_input") or {}).get("file_path")
    if not fp:
        return 0

    try:
        rel = Path(fp).resolve().relative_to(cwd.resolve()).as_posix()
    except Exception:
        return 0

    if rel in set(st.get("scope_files") or []):
        return 0

    msg = (f"[debug-scope] {rel} 不在当前范围（改动文件）内；"
           f"同一问题已试 {tries} 次。若并非必需，先走 L1（grep 调用方）；"
           f"确需扩大范围请说明理由，或运行 scope.py escalate on。")
    return emit(msg)


if __name__ == "__main__":
    sys.exit(main())
