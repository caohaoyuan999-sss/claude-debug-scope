---
name: debug-scope
description: 调试、排查 bug 时按"地图 + 增量 + 阶梯"工作，避免每次重新读整个项目；读过的代码沉淀成项目内文件，跨会话、跨压缩都不丢。当用户贴报错/traceback、说"跑不通 / 不工作 / 报错了 / 崩溃 / 异常 / 怎么又错了 / 帮我看看这段"，要求排查 bug，或说"解决了 / 好了"时使用。
---

# Debug Scope

目标：同一个问题不让 Claude 反复读整个项目。第一次把项目读成"地图"，之后只读改动部分；同一问题卡住 3 次才扩大范围。

## 项目内文件

| 路径 | 作用 | 谁维护 |
|---|---|---|
| `.claude/code-map.md` | 项目地图：文件结构 + 符号 + 行号 | `scope.py scan` |
| `.claude/debug-journal.md` | 问题日志，**只追加，永不改写** | 脚本 |
| `.claude/scope-state.json` | 状态机（issue / baseline / scope） | 脚本，**禁止手改** |
| `.claude/debug-scope/scope.py` | 脚本本体 | 从本 skill 复制一次 |

## 第一次使用（项目里还没有地图）

1. 把本 skill 目录下的 `scripts/scope.py` 复制到项目的 `.claude/debug-scope/scope.py`
2. `python .claude/debug-scope/scope.py init`
3. `python .claude/debug-scope/scope.py scan` —— 生成地图（只有结构，不含源码原文）
4. `python .claude/debug-scope/scope.py snapshot` —— 记为 baseline，即用户"保存并运行过一次"的那一刻
5. **读 `.claude/code-map.md` 建立全局认知，不要读源码全文**
6. 只读报错相关的 1–3 个文件

之后不再需要全量扫描。

## 每次收到问题

1. `python .claude/debug-scope/scope.py changed` —— 拿到相对 baseline 的改动集
2. `python .claude/debug-scope/scope.py issue new "<一句话描述>"`（上一个 issue 未关闭时会被自动标为 superseded）
3. 读：改动文件 + 报错里点名的文件（L0）
4. 不够 → L1：grep 找调用方 / import / 配置，只读命中的函数
5. 读了新文件就 `scan` 一次（只重写 sha 变了的块，不会整篇重写）

## 读取阶梯

- **L0**：改动文件 + 报错直接指到的文件
- **L1**：L0 的直接依赖（grep 调用方、import、配置文件）
- **L2**：全量。**只在**地图缺失、或同一问题 3 次未解决、**且用户明确同意**后使用

每次回答的第一行说明范围，例如：`范围：L0（2 个文件）`。

## 假设与计数

每提出一个可证伪的假设（"我怀疑是 X 导致的"）就记一次：

```bash
python .claude/debug-scope/scope.py issue tried "怀疑 X 导致 Y"
```

- 连续 2 次假设失败 → 先走 L1，不要跳到全量
- 第 3 次仍未解决 → **停下来问用户**："已试 3 次还没解决，要不要全量读一遍？"；用户同意后运行 `escalate on`

## 什么算"解决"

| 信号 | 动作 | 算解决 |
|---|---|---|
| 用户说"解决了 / 好了" | `issue fixed --confirmed` | ✅ |
| 报错消失 / 测试转绿（有实际输出为证） | `issue fixed` → 进入 pending-confirm | ⏳ 待用户确认 |
| 用户不提这个问题、直接问新问题 | `issue close`（未确认关闭） | ❌ 不算，但关闭并清零 |
| 我口头说"应该好了" | 不记录 | ❌ |

**禁止**在没有客观依据时自己宣布问题解决。`fixed` 和"未确认关闭"必须分开记，这个比例是以后优化本流程的唯一依据。

## 记录纪律

- `debug-journal.md` 只追加，不改旧行
- `code-map.md` 只替换 sha 变化的文件块，不整篇重写
- 地图里存"结构 + 符号 + 行号"，**不存源码原文**：原文会过期，也会吃掉上下文

## 向用户要的三件套

报错原文 / 复现步骤 / 刚改了什么。缺了只问一次，不要猜。
