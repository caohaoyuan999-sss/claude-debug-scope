# debug-scope

让 Claude Code 排查 bug 时**不要每次都重读整个项目**：第一次读成"地图"，之后只读改动部分，同一问题卡住 3 次才建议全量。

## 它解决什么

- 每次问 bug，Claude 都从头 grep/读一堆文件，慢且贵
- 长会话里上下文被压缩，刚读过的代码"忘了"
- 修好了没有客观记录，下次又从头来

做法：把项目结构沉淀成**文件**（不是靠记忆），把"改了哪些文件"用 hash 基线算出来，把每个问题的尝试次数记成状态机。

## 安装

```bash
# 在 Claude Code 里
/plugin marketplace add <你的GitHub用户名>/claude-debug-scope
/plugin install debug-scope@debug-scope-marketplace
```

## 使用

第一次在一个项目里用它时，Claude 会：

1. 复制 `scope.py` 到项目的 `.claude/debug-scope/`
2. 跑 `init` / `scan` / `snapshot`，生成：

| 文件 | 内容 |
|---|---|
| `.claude/code-map.md` | 项目地图：每个文件的 sha、行数、符号和行号 |
| `.claude/debug-journal.md` | 问题日志，只追加 |
| `.claude/scope-state.json` | 当前问题、尝试次数、改动基线 |

3. 读地图建立全局认知，只读报错相关的 1–3 个文件

之后每次问 bug，Claude 只跑 `changed` 拿改动集，读改动文件 + 报错指到的文件。

建议把生成物加进项目 `.gitignore`（个人调试记录，通常不该提交）：

```gitignore
.claude/code-map.md
.claude/debug-journal.md
.claude/scope-state.json
```

## 手动命令

```bash
python .claude/debug-scope/scope.py init      # 初始化
python .claude/debug-scope/scope.py scan      # 生成/增量更新地图
python .claude/debug-scope/scope.py snapshot  # 记录 baseline（=「保存并运行过一次」）
python .claude/debug-scope/scope.py changed   # 列出相对 baseline 的改动

python .claude/debug-scope/scope.py issue new "登录页 500"
python .claude/debug-scope/scope.py issue tried "怀疑 token 过期没刷新"
python .claude/debug-scope/scope.py issue fixed --confirmed   # 用户说「好了」
python .claude/debug-scope/scope.py issue fixed               # 待确认（有报错消失/测试转绿为证）
python .claude/debug-scope/scope.py issue confirm
python .claude/debug-scope/scope.py issue close               # 没确认就换问题
python .claude/debug-scope/scope.py issue status

python .claude/debug-scope/scope.py escalate on|off           # 允许/禁止全量读取
```

## 读取阶梯

| 级别 | 读什么 | 何时 |
|---|---|---|
| L0 | 改动文件 + 报错指到的文件 | 默认 |
| L1 | L0 的直接调用方/被调用方（grep） | L0 解释不通 |
| L2 | 全量 | 地图缺失，或 3 次未解决且用户同意 |

## 怎样才算"解决"

| 信号 | 结果 |
|---|---|
| 用户说"解决了 / 好了" | `fixed` |
| 报错消失 / 测试转绿（有输出为证） | `pending-confirm`，等用户确认 |
| 用户不提这个、直接问新问题 | `closed-unconfirmed`（不算解决，但关闭计数） |
| Claude 说"应该好了" | 不算 |

`fixed` 和 `closed-unconfirmed` 分开记，比例是以后调参的唯一依据。

## Hook 行为

`hooks/hooks.json` 注册了一个 `PreToolUse(Read)` 的**软提醒**：

- 只在存在 `.claude/scope-state.json` 且当前问题 `open`、已试 ≥ 2 次时触发
- 只在读**改动集之外**的文件时触发
- 只输出提示，**不拦截**（`permissionDecision: allow`）
- 运行 `escalate on` 后彻底静默

## 让它在写代码时也生效

skill 是按描述匹配触发的，不是常驻。想更稳，在项目的 `CLAUDE.md` 加三行：

```markdown
## 调试
- 修 bug 先走 debug-scope：改动文件 + 报错文件（L0），不要全量读
- 同一问题 3 次未解决，先问我要不要全量
- 我说"解决了/好了"才记 fixed
```

## 已知限制

- 符号提取是正则启发式，不是语法分析；语言不在支持列表里时只记 sha/行数
- 只按文件粒度算改动，不做函数级 diff
- 没有 `git` 也能用（用的是 sha256 基线），但有 git 会更方便回滚

## License

MIT
