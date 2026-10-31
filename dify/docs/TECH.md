# 一页技术说明：记忆酒馆

## 结构

```
Dify Chatflow                          酒馆后端 (FastAPI, 127.0.0.1:8770)
┌───────────────┐   form POST /recall   ┌───────────────────────────────┐
│ Start         │ ────────────────────► │ 读 seekdb: players + lore     │
│ (player_id)   │ ◄──────────────────── │ PowerContext: memory/search   │
│ 回忆旧账      │      JSON context     │ 组装 lore / memories / 账本   │
│ 老巴 (LLM)    │                       └───────────────────────────────┘
│ 记账与存忆    │   form POST /remember  ┌───────────────────────────────┐
│ Answer        │ ────────────────────► │ 规则结算 → UPDATE players     │
└───────────────┘ ◄──────────────────── │ INSERT turns                  │
                                        │ PowerContext: memory/remember │
                                        └───────────────────────────────┘
```

## 一次回合的数据流

1. **Recall（读）**
   - `players`：`debt / grudge / visits / epoch / pc_scope_id`（seekdb）
   - `lore`：24 张素材卡按关键词命中排序，取 3 条；`rule` 取 2 条；另有按消息哈希选出的 `daily_special`（seekdb）
   - `turns`：当前 epoch 最近 3 条账本摘要（seekdb）
   - `memory/search`：以“玩家消息 + 欠账 + 仇怨 + 上次”为 query，取 5 条旧回合（PowerContext）
   - 输出 `greeting_hint`，明确告诉 LLM 先翻旧账还是先招呼生客。
2. **LLM**：老巴的 system prompt 同时看到上述 JSON 与硬性规则（必须提欠账、必须引用非空 memories、不得自行算账）。
3. **Remember（写）**
   - `tavern.analyze` 用关键词判定 `credit / repay / repay_apology / lie / theft / apology / purchase / gossip / chat`，更新 `debt`、`grudge`（夹在 0 和 9 之间）并 `INSERT turns`（seekdb）。
   - 把“玩家原话 + 老巴台词 + 判定 + 余额”写成一条 episodic memory 写入 PowerContext。
   - 返回纯文本账本行，Dify 直接拼在 Answer 里。

## seekdb 表

| 表 | 用途 | 关键列 |
| --- | --- | --- |
| `lore` | 酒单、传闻、店规、常客、秘密 | `category, title, content, keywords, price` |
| `players` | 每个玩家的账本与记忆指针 | `player_id, epoch, pc_scope_id, visits, debt, grudge, last_seen, memo` |
| `turns` | 回合日志（规则证据） | `player_id, epoch, message, reply, intent, delta_debt, delta_grudge` |

`epoch` 是重置代数：`/reset` 会 `epoch+1`、清空 `pc_scope_id` 与账本。新 scope 标题带随机后缀，避免与历史 scope 的幂等键碰撞；旧记忆仍留在 PowerContext，但不再被当前 epoch 查询。

## PowerContext 作用域

- 标题：`tavern-<player_id>-e<epoch>-<nonce>`，每个玩家一个 scope；
- 关联方式：创建后把 `scope_id` 写回 `players.pc_scope_id`；后端重启后从 seekdb 读回并复用；
- 写入：`POST /v1/memory/remember`（kind=`episodic`，带 reason）；
- 读取：`POST /v1/memory/search`（text 模式，limit=5）；
- 为什么不用 Dify 会话变量：Dify 新会话会丢变量，而作品要求跨会话记仇，所以记忆必须落在外部服务。

## Dify 节点

| 节点 | 类型 | 作用 |
| --- | --- | --- |
| Start | start | 收 `player_id`；对话内容走 `sys.query` |
| 回忆旧账 | http-request | `POST {TAVERN_API}/recall`，`x-www-form-urlencoded`（避免消息中的引号破坏 JSON） |
| 老巴（记忆驱动） | llm | system prompt 注入账本/素材/旧记忆，`temperature=0.85` |
| 记账与存忆 | http-request | `POST {TAVERN_API}/remember`，提交 `player_id/message/reply`，开启 2 次重试 |
| Answer | answer | `llm.text + remember.body` |

`TAVERN_API` 是 Dify 环境变量，导入后可在 UI 修改；DSL 不包含任何密钥。

## 规则边界

- LLM 只负责“说话”，不负责数字；余额、仇怨、是否赊账都由后端确定性结算，换模型不影响账本。
- 输入校验：`player_id` 仅允许字母/数字/下划线/连字符/汉字；消息 ≤2000 字，台词 ≤4000 字；非法输入返回 4xx。
- 失败降级：PowerContext 不可用时 recall 仍返回 seekdb 账本与 `memory_warning`，remember 仍落账；但验证样例要求 `powercontext_ok=true`。
- 单进程：seekdb 句柄与线程锁不跨进程，生产化时应改为 seekdb server 模式并加鉴权。
