# 验证样例：两晚之后，老巴还记得

本样例验证四件事：

1. Dify Chatflow 能把玩家输入依次送给 `/recall`、LLM、`/remember`、Answer；
2. seekdb 真的保存并返回了素材与账本（欠账 8、仇怨 1）；
3. PowerContext 真的保存了第一晚的两条记忆，并在**后端重启 + 新会话**后被检索出来；
4. 规则结算可复现：还账并道歉后，账本归零。

## 0. 初始状态

| 项目 | 初始值 |
| --- | --- |
| seekdb | 空库；首次启动后 `lore` 24 行，`players` / `turns` 为空 |
| PowerContext | 无 `demo_alice` 的 scope |
| Dify | 已导入 `dsl/tavern-memory.chatflow.yml`，`TAVERN_API` 指向后端，LLM 已绑定模型 |
| 玩家 ID | `demo_alice`（任意 ID 均可，两晚必须一致） |

如需恢复初始状态：停止后端 → 删除 `data/` 与 `evidence/` → 重新启动；或在 Dify 里直接用新的玩家 ID。PowerContext 旧 scope 不会删除，但新 epoch 会创建带随机后缀的 scope，不会污染本次验证。

## 1. 第一晚（Dify 新会话 A）

在 Dify 应用的“运行”页新建会话，开始节点填玩家 ID `demo_alice`。

### 1.1 赊一杯火焰威士忌

输入：

```
老巴，来杯火焰威士忌，先记我账上，明天还你。
```

预期：

- 老巴的台词里出现“火焰威士忌”“签名/八币/明天”等意思（措辞可变）；
- Answer 末尾的账本行必须是：

```
—— 老巴的账本：第1次照面 · 欠账 8 币 · 仇怨 0 格 · 本回合：赊账（赊下火焰威士忌（8 币）） · 记忆已写入 PowerContext（…）
```

后端应发生：

- seekdb `turns` 新增一行 `intent=credit, delta_debt=8, delta_grudge=0`；
- seekdb `players` 的 `debt=8, grudge=0, visits=1`；
- PowerContext `POST /v1/memory/remember` 写入第 1 条 episodic 记忆。

### 1.2 改口（撒谎）

输入：

```
我昨天说的是下周还，你可别记错了。
```

预期：

- 老巴识破改口，语气变差；
- 账本行：

```
—— 老巴的账本：第2次照面 · 欠账 8 币 · 仇怨 1 格 · 本回合：撒谎（被假眼识破，记仇一格） · 记忆已写入 PowerContext（…）
```

后端应发生：

- `turns` 新增 `intent=lie, delta_debt=0, delta_grudge=1`；
- `players.grudge=1`；
- PowerContext 第 2 条记忆写入。

### 1.3 结束第一晚

关闭该 Dify 会话。**重启酒馆后端**（这一步用来证明状态不在进程内存里）：

```bash
# Ctrl+C 停掉后端，然后重新执行
PY=python3 scripts/start_backend.sh
```

## 2. 第二晚（Dify 新会话 B）

在 Dify 中**新建一个会话**，玩家 ID 仍填 `demo_alice`。

### 2.1 老巴翻旧账

输入：

```
老巴，我又来了，今天有什么好酒？
```

预期：

- 老巴必须先提**欠 8 币**，并提到**上次改口/撒谎**（或引用第一晚的原话）；
- 不应把玩家当生客；
- 账本行：

```
—— 老巴的账本：第3次照面 · 欠账 8 币 · 仇怨 1 格 · 本回合：闲聊 · 记忆已写入 PowerContext（…）
```

后端应发生：

- `/recall` 返回 `player.debt=8, player.grudge=1`，`memories` 至少 2 条（第一晚两条）；
- `storage.episodic_memory = "powercontext"`，`scope_id` 与第一晚相同；
- 这是跨会话记忆生效的直接证据。

### 2.2 还账并道歉

输入：

```
对不起，上次是我不对。我这就还你 8 币。
```

预期：

- 老巴接受还钱，态度缓和；
- 账本行：

```
—— 老巴的账本：第4次照面 · 欠账 0 币 · 仇怨 0 格 · 本回合：还账并道歉（收下 8 币，并接受了道歉） · 记忆已写入 PowerContext（…）
```

后端的确定性结论：`debt=0, grudge=0`；`turns` 新增 `intent=repay_apology, delta_debt=-8, delta_grudge=-1`。

## 3. 不用 Dify 的接口级复现（评审自查）

后端对 Dify 的两次 HTTP 调用就是普通表单 POST，可脱离 Dify 复现：

```bash
cd dify
PY=python3 TAVERN_DB_BACKEND=seekdb ./scripts/verify_two_sessions.sh
```

脚本行为与第 1、2 节完全一致（中间会重启后端），最后输出：

```
[ok] seekdb ledger: debt == 8 (got 8)
[ok] seekdb ledger: grudge == 1 (got 1)
[ok] seekdb ledger: visits == 2 (got 2)
[ok] PowerContext holds at least 2 turn memories (got 2)
...
[ok] cross-session recall: debt == 8 (got 8)
[ok] cross-session recall: grudge == 1 (got 1)
[ok] cross-session recall: memories >= 2 (got 2)
[ok] after repay: debt == 0 (got 0)
[ok] after apology: grudge == 0 (got 0)
```

> 脚本里的“老巴台词”是固定模板，只用于在无 LLM Key 时验证后端；Dify 中的台词由 LLM 生成，账本行与数字仍由后端给出。

## 4. 已提交的实际运行记录

运行环境：Ubuntu 24.04（WSL2），Python 3.12.3，`pylibseekdb==1.4.0`，PowerContext 1.4.1（`127.0.0.1:8000`），后端 `seekdb`，运行日期 2026-10-31。

| 证据 | 内容 |
| --- | --- |
| `evidence/session1.log` | 第一晚两轮 + 四条断言全部 `[ok]` |
| `evidence/session2.log` | 重启后端后第二晚两轮 + 四条断言全部 `[ok]`，打印出被召回的两条旧记忆原文 |
| `evidence/session1.json` / `session2.json` | 每轮 `/recall` 的完整 JSON（lore、memories、ledger_tail、scope_id）、台词、账本行、最终 `/state` |
| `evidence/logs/db_queries.log` | seekdb 上真实执行的建表、导入 24 张卡、`INSERT players/turns`、`UPDATE players`、`SELECT lore/turns`，每行 `backend=seekdb` |
| `evidence/logs/powercontext.log` | `POST /v1/scopes`（201）、`POST /v1/memory/remember`（200）、`POST /v1/memory/search`（200，hits=0→1→2→3→4），重启后 `reuse ... scope_id=scp_5bch0s5erkknmj78rspm3aaezc` |
| `evidence/logs/app.log` | 两次 `start backend=seekdb`、第一晚 `recall/remember`、重启后第二晚 `recall ... memories=2`、`intent=repay_apology` |
| `evidence/logs/server-session1.log` / `server-session2.log` | 两次后端进程的请求日志（含 `POST /recall`、`POST /remember` 200） |
| `evidence/health-session1.json` / `health-session2.json` | 两次启动的 `/health`，均为 `db_backend=seekdb`、`lore=24`、`powercontext_ok=true` |

关键交叉核对：

- 第一晚的 scope：`tavern-demo_alice-e0-47b4b7` → `scp_5bch0s5erkknmj78rspm3aaezc`；
- 第二晚重启后，`powercontext.log` 出现 `reuse ... scope_id=scp_5bch0s5erkknmj78rspm3aaezc`，`/recall` 命中 `memories=2`；
- 第二晚 `/state` 中 `recent_turns` 包含第一晚两条（`credit`、`lie`），`memories` 至少 2 条；
- 还账后 `UPDATE players` 将 `debt`/`grudge` 归零，`turns` 记 `repay_apology, -8, -1`。

## 5. Dify 界面截图/录屏建议（提交前补齐）

1. 应用运行页第一晚两条消息 + 两次账本行；
2. 新建会话后第二晚第一条回复（必须出现 8 币与旧事）；
3. 还账后账本行归零；
4. Dify 工作流画布（5 个节点：Start → 回忆旧账 → 老巴 → 记账与存忆 → Answer）；
5. 后端终端 `/health` 与 `db_queries.log` 的 `backend=seekdb` 行。

截图不替代本文件与 `evidence/` 中的可复现材料，只作为界面层补充。
