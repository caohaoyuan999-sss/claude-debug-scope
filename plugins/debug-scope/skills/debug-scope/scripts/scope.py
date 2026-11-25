#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""debug-scope：项目地图 / 改动基线 / 问题状态机。用法见 SKILL.md。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

STATE_DIR = Path(".claude")
STATE_FILE = STATE_DIR / "scope-state.json"
MAP_FILE = STATE_DIR / "code-map.md"
JOURNAL_FILE = STATE_DIR / "debug-journal.md"

SKIP_DIRS = {"node_modules", "dist", "build", "target", "out", "vendor",
             "coverage", "venv", "env", "site-packages"}
CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte",
    ".java", ".kt", ".kts", ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".hpp",
    ".cs", ".php", ".rb", ".swift", ".m", ".mm", ".scala", ".sh", ".bash",
    ".sql", ".lua", ".dart",
}
MAX_FILE_BYTES = 400_000
MAX_SYMBOLS = 40
MAX_INDENT = 4

SYMBOL_PATTERNS = {
    "py": [
        ("def", re.compile(r"^(?P<indent>[ \t]*)(?:async[ \t]+)?def[ \t]+(?P<name>\w+)")),
        ("class", re.compile(r"^(?P<indent>[ \t]*)class[ \t]+(?P<name>\w+)")),
    ],
    "js": [
        ("fn", re.compile(r"^(?P<indent>[ \t]*)(?:export[ \t]+)?(?:default[ \t]+)?(?:async[ \t]+)?function[ \t]+(?P<name>\w+)")),
        ("class", re.compile(r"^(?P<indent>[ \t]*)(?:export[ \t]+)?(?:default[ \t]+)?class[ \t]+(?P<name>\w+)")),
        ("fn", re.compile(r"^(?P<indent>[ \t]*)(?:export[ \t]+)?(?:const|let|var)[ \t]+(?P<name>\w+)[ \t]*=[ \t]*(?:async[ \t]*)?(?:\([^)]*\)[ \t]*=>|function[ \t]+|\()")),
    ],
    "jvm": [
        ("method", re.compile(r"^(?P<indent>[ \t]*)(?:public|private|protected|static|final|abstract|synchronized|native|default|override|suspend)[ \t]+[\w<>\[\],\.\?\s]+[ \t]+(?P<name>\w+)[ \t]*\(")),
        ("class", re.compile(r"^(?P<indent>[ \t]*)(?:public|private|protected|abstract|final|static|sealed|data|inner)?[ \t]*(?:class|interface|enum|record|object)[ \t]+(?P<name>\w+)")),
    ],
    "go": [
        ("fn", re.compile(r"^(?P<indent>[ \t]*)func[ \t]+(?:\([^)]*\)[ \t]*)?(?P<name>\w+)")),
        ("type", re.compile(r"^(?P<indent>[ \t]*)type[ \t]+(?P<name>\w+)")),
    ],
    "rs": [
        ("fn", re.compile(r"^(?P<indent>[ \t]*)(?:pub[ \t]+)?(?:async[ \t]+)?fn[ \t]+(?P<name>\w+)")),
        ("struct", re.compile(r"^(?P<indent>[ \t]*)(?:pub[ \t]+)?(?:struct|enum|trait|impl)[ \t]+(?P<name>\w+)")),
    ],
    "c": [
        ("fn", re.compile(r"^(?P<indent>[ \t]*)(?:static[ \t]+|inline[ \t]+|extern[ \t]+)*[A-Za-z_][\w \t\*&:<>]*[ \t\*]+(?P<name>[A-Za-z_]\w*)[ \t]*\([^;]*$")),
    ],
    "rb": [
        ("def", re.compile(r"^(?P<indent>[ \t]*)(?:def|function|func)[ \t]+(?P<name>\w+)")),
        ("class", re.compile(r"^(?P<indent>[ \t]*)(?:class|module)[ \t]+(?P<name>\w+)")),
    ],
    "sh": [
        ("fn", re.compile(r"^(?P<indent>[ \t]*)(?:function[ \t]+)?(?P<name>[A-Za-z_]\w*)[ \t]*\(\)")),
    ],
}

GROUP_BY_EXT = {
    ".py": "py",
    ".js": "js", ".jsx": "js", ".ts": "js", ".tsx": "js",
    ".mjs": "js", ".cjs": "js", ".vue": "js", ".svelte": "js",
    ".java": "jvm", ".kt": "jvm", ".kts": "jvm", ".cs": "jvm", ".scala": "jvm",
    ".go": "go",
    ".rs": "rs",
    ".c": "c", ".h": "c", ".cc": "c", ".cpp": "c", ".hpp": "c",
    ".m": "c", ".mm": "c",
    ".php": "rb", ".rb": "rb",
    ".sh": "sh", ".bash": "sh",
}


def now_str() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_state(root: Path) -> dict:
    p = root / STATE_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": 1, "mode": "warn", "escalate": False,
            "baseline": {}, "scope_files": [], "issue": None, "history": []}


def save_state(root: Path, state: dict) -> None:
    p = root / STATE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_journal(root: Path, issue_id, event: str, detail: str = "") -> None:
    p = root / JOURNAL_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("# debug-journal\n\n", encoding="utf-8")
    with p.open("a", encoding="utf-8") as f:
        f.write(f"- {now_str()} | {issue_id or '-'} | {event} | {detail.strip()}\n")


def iter_code_files(root: Path):
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d not in SKIP_DIRS)
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if p.suffix.lower() not in CODE_EXTS:
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield p.relative_to(root).as_posix(), p


def file_sha(path: Path):
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def symbols_for(path: Path):
    group = GROUP_BY_EXT.get(path.suffix.lower())
    if not group:
        return [], 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], 0
    lines = text.splitlines()
    found, seen = [], set()
    for lineno, line in enumerate(lines, 1):
        for kind, rx in SYMBOL_PATTERNS[group]:
            m = rx.match(line)
            if not m:
                continue
            if len(m.group("indent").expandtabs(4)) > MAX_INDENT:
                break
            name = m.group("name")
            if name in seen:
                break
            seen.add(name)
            found.append(f"- `L{lineno}` {kind} `{name}`")
            break
        if len(found) >= MAX_SYMBOLS:
            found.append("- …（符号过多，已截断）")
            break
    return found, len(lines)


def parse_map(text: str):
    shas, bodies = {}, {}
    cur, sha, buf = None, None, []
    for line in text.splitlines(keepends=True):
        m = re.match(r"<!-- file: (.+?) \| sha: ([0-9a-f]{8,})", line)
        if m:
            if cur:
                shas[cur] = sha
                bodies[cur] = "".join(buf)
            cur, sha, buf = m.group(1), m.group(2), [line]
        elif cur is not None:
            buf.append(line)
    if cur:
        shas[cur] = sha
        bodies[cur] = "".join(buf)
    return shas, bodies


def current_shas(root: Path) -> dict:
    out = {}
    for rel, p in iter_code_files(root):
        sha = file_sha(p)
        if sha:
            out[rel] = sha
    return out


def cmd_init(root: Path) -> None:
    (root / STATE_DIR).mkdir(parents=True, exist_ok=True)
    if not (root / STATE_FILE).exists():
        save_state(root, load_state(root))
    if not (root / JOURNAL_FILE).exists():
        (root / JOURNAL_FILE).write_text("# debug-journal\n\n", encoding="utf-8")
    print(f"已初始化 {(root / STATE_DIR).as_posix()}/")
    print("建议加入 .gitignore：")
    for f in (MAP_FILE, JOURNAL_FILE, STATE_FILE):
        print(f"  {f.as_posix()}")


def cmd_scan(root: Path) -> None:
    mp = root / MAP_FILE
    old_shas, old_bodies = ({}, {})
    if mp.exists():
        old_shas, old_bodies = parse_map(mp.read_text(encoding="utf-8"))
    parts, reused, updated = [], 0, 0
    for rel, path in iter_code_files(root):
        sha = file_sha(path)
        if sha is None:
            continue
        if old_shas.get(rel) == sha and rel in old_bodies:
            parts.append(old_bodies[rel])
            reused += 1
            continue
        syms, nlines = symbols_for(path)
        block = [f"<!-- file: {rel} | sha: {sha} | lines: {nlines} -->\n",
                 f"### {rel}\n"]
        if syms:
            block.extend(s + "\n" for s in syms)
        else:
            block.append("- （无可识别符号）\n")
        parts.append("".join(block) + "\n")
        updated += 1
    header = (
        "# 项目地图\n\n"
        "> debug-scope 生成，勿手改。sha 与磁盘不一致说明该块已过期。\n"
        f"> 更新：{now_str()}　文件数：{len(parts)}\n\n"
    )
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(header + "".join(parts), encoding="utf-8")
    print(f"地图已更新：{len(parts)} 个文件（复用 {reused}，重写 {updated}）→ {MAP_FILE.as_posix()}")


def cmd_snapshot(root: Path) -> None:
    st = load_state(root)
    shas = current_shas(root)
    st["baseline"] = shas
    st["scope_files"] = []
    save_state(root, st)
    print(f"baseline 已记录：{len(shas)} 个文件")


def cmd_changed(root: Path) -> None:
    st = load_state(root)
    base = st.get("baseline") or {}
    if not base:
        print("还没有 baseline。先运行：scope.py snapshot")
        return
    cur = current_shas(root)
    modified = [r for r, s in sorted(base.items()) if r in cur and cur[r] != s]
    deleted = [r for r in sorted(base) if r not in cur]
    added = [r for r in sorted(cur) if r not in base]
    scope = modified + added
    st["scope_files"] = scope
    save_state(root, st)
    print(f"改动 {len(scope)} 个文件（相对 baseline）")
    for r in modified:
        print(f"  M {r}")
    for r in added:
        print(f"  A {r}")
    for r in deleted:
        print(f"  D {r}")


def active_issue(st: dict):
    iss = st.get("issue")
    if iss and iss.get("state") in ("open", "pending-confirm"):
        return iss
    return None


def close_issue(root: Path, st: dict, final_state: str, detail: str = "") -> None:
    iss = st.get("issue")
    if not iss:
        return
    iss["state"] = final_state
    iss["closed"] = now_str()
    st.setdefault("history", []).append(iss)
    st["issue"] = None
    st["escalate"] = False
    append_journal(root, iss.get("id"), final_state, detail)
    save_state(root, st)


def cmd_issue(root: Path, args) -> None:
    st = load_state(root)
    action = args.action
    text = (args.text or "").strip()

    if action == "new":
        cur = active_issue(st)
        if cur:
            close_issue(root, st, "superseded", f"被新问题取代：{text}")
        iid = datetime.now().strftime("%Y%m%d-%H%M%S")
        st["issue"] = {"id": iid, "desc": text, "state": "open", "tries": 0,
                       "hypotheses": [], "opened": now_str()}
        save_state(root, st)
        append_journal(root, iid, "open", text)
        print(f"开启 issue {iid}：{text}")
        return

    if action == "status":
        iss = st.get("issue")
        print(f"issue    : {iss['id'] if iss else '（无）'}")
        if iss:
            print(f"描述     : {iss.get('desc', '')}")
            print(f"状态     : {iss.get('state')}")
            print(f"已试次数 : {iss.get('tries', 0)}")
            for i, h in enumerate(iss.get("hypotheses") or [], 1):
                print(f"  {i}. {h}")
        print(f"escalate : {st.get('escalate')}")
        print(f"改动范围 : {len(st.get('scope_files') or [])} 个文件")
        print(f"历史     : {len(st.get('history') or [])} 条")
        return

    iss = active_issue(st)
    if not iss:
        sys.exit('没有进行中的 issue，先运行：scope.py issue new "<描述>"')

    if action == "tried":
        iss["tries"] = int(iss.get("tries", 0)) + 1
        iss.setdefault("hypotheses", []).append(text)
        append_journal(root, iss["id"], "tried", text)
        save_state(root, st)
        print(f"已记录假设 #{iss['tries']}：{text}")
        if iss["tries"] >= 3 and not st.get("escalate"):
            print("⚠ 已试 3 次。先问用户是否全量读取，得到同意后运行：escalate on")
        return

    if action == "fixed":
        if args.confirmed:
            close_issue(root, st, "fixed", text or "用户确认解决")
            st["baseline"] = current_shas(root)
            save_state(root, st)
            print("已标记 fixed，并刷新 baseline")
        else:
            iss["state"] = "pending-confirm"
            append_journal(root, iss["id"], "pending-confirm", text or "有客观依据，待用户确认")
            save_state(root, st)
            print("已标记 pending-confirm：等用户说「好了」后运行 issue confirm")
        return

    if action == "confirm":
        if iss.get("state") != "pending-confirm":
            sys.exit("当前 issue 不在 pending-confirm 状态")
        close_issue(root, st, "fixed", text or "用户确认解决")
        st["baseline"] = current_shas(root)
        save_state(root, st)
        print("已确认 fixed，并刷新 baseline")
        return

    if action == "close":
        close_issue(root, st, "closed-unconfirmed", text or "用户未确认，直接问了新问题")
        st["baseline"] = current_shas(root)
        save_state(root, st)
        print("已关闭（未确认），并刷新 baseline")
        return

    sys.exit(f"未知动作：{action}")


def cmd_escalate(root: Path, value: str) -> None:
    st = load_state(root)
    st["escalate"] = value == "on"
    save_state(root, st)
    append_journal(root, (st.get("issue") or {}).get("id"), "escalate", value)
    print(f"escalate = {st['escalate']}"
          f"（{'允许全量读取' if st['escalate'] else '恢复最小范围'}）")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scope.py", description="debug-scope 状态机")
    ap.add_argument("--root", default=".", help="项目根目录，默认当前目录")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("scan")
    sub.add_parser("snapshot")
    sub.add_parser("changed")
    p_issue = sub.add_parser("issue")
    p_issue.add_argument("action", choices=["new", "tried", "fixed", "confirm", "close", "status"])
    p_issue.add_argument("text", nargs="?", default="")
    p_issue.add_argument("--confirmed", action="store_true", help="用户已确认解决")
    p_esc = sub.add_parser("escalate")
    p_esc.add_argument("value", choices=["on", "off"])

    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"目录不存在：{root}")

    if args.cmd == "init":
        cmd_init(root)
    elif args.cmd == "scan":
        cmd_scan(root)
    elif args.cmd == "snapshot":
        cmd_snapshot(root)
    elif args.cmd == "changed":
        cmd_changed(root)
    elif args.cmd == "issue":
        cmd_issue(root, args)
    elif args.cmd == "escalate":
        cmd_escalate(root, args.value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
