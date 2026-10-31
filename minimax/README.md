# SDD 上下文模块（MiniMax × seekdb × PowerContext）

围绕规格驱动开发（SDD）的工程上下文模块：给定一个开发任务，它从工程资料库中检索**当前有效**的规格、相关代码与测试，组装成有界的开发上下文，交给 **MiniMax** 生成代码修改，应用后用目标测试与回归测试验证，并把任务进展写入 **PowerContext**，供后续运行读取并继续使用。

任务场景：为样例任务板 `list_tasks` 增加 `status` 筛选（REQ-003），筛选必须发生在排序之后、分页之前，且不破坏既有排序/分页/校验行为。

```
任务 → seekdb 检索(spec/code/test) → 上下文 → MiniMax → unified diff → 应用 → 目标测试 + 回归测试
                                                        ↓
                                    PowerContext 保存进展 → 新进程读取 → 注入下一次上下文
```

## 1. 目录结构

```
minimax/
├── sddctx/                  # 上下文模块（CLI：python -m sddctx）
│   ├── config.py            # 路径与环境变量
│   ├── db.py                # seekdb/sqlite 存储与 LIKE 检索（Python DB-API，PyMySQL）
│   ├── ingest.py            # 规格/代码/测试切块入库（ast + 标题切分）
│   ├── context.py           # 关键词抽取、检索挑选、上下文渲染
│   ├── minimax_client.py    # MiniMax HTTP 客户端（官方 / OpenAI 兼容）+ 离线回放
│   ├── agent.py            # 提示词、diff 应用、pytest 执行、失败反馈重试
│   ├── state.py            # PowerContext HTTP 状态保存/读取（含 local 兜底）
│   ├── verify.py           # 端到端验收
│   ├── cli.py              # 调用入口
│   └── golden_patch.diff   # 离线回放用的参考补丁
├── sample/                  # 验证样例工程（可独立运行）
│   ├── specs/taskboard.md  # REQ-001 ~ REQ-004
│   ├── src/taskboard/      # models.py, service.py
│   ├── tests/              # test_target_filter.py, test_regression.py
│   └── pytest.ini
├── docs/
│   ├── sample-task.md      # 验证样例：任务、有效规格、初始数据、步骤、预期、重置
│   └── TECH.md             # 一页技术说明
└── artifacts/              # 运行产物：上下文、提示词、差异、测试日志、使用记录
```

## 2. 依赖与版本

| 组件 | 版本 / 接入方式 | 作用 |
| --- | --- | --- |
| Python | 3.11+（开发机验证 3.13） | 运行时 |
| seekdb | `pylibseekdb` + `pymysql`（嵌入式，Linux） | 存储并检索工程资料 |
| PowerContext | 1.4.1，本地 Server + HTTP API | 保存并复用任务状态 |
| MiniMax | HTTP 调用 `POST /v1/text/chatcompletion_v2`（或 OpenAI 兼容 `/v1/chat/completions`） | 生成代码修改 |
| pytest | 9.x | 目标测试与回归测试 |

```bash
cd minimax
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

> `pylibseekdb` 仅提供 Linux wheel。在其他平台做本地联调时，可临时使用 `SDDCTX_DB_BACKEND=sqlite`，该模式不用于提交验收。
>
> 个别环境里 `powercontext[server]` 的依赖解析会漏装 `typer`/`mcp`，若 CLI 报 `ModuleNotFoundError`，执行 `pip install typer mcp` 即可（`requirements.txt` 已显式列出）。

## 3. 配置
```bash
# 数据库（默认嵌入式 seekdb，数据目录 .data/seekdb，库名 sddctx）
export SDDCTX_DB_BACKEND=seekdb
export SDDCTX_DB_PATH="$PWD/.data/seekdb"
export SDDCTX_DB_NAME=sddctx

# MiniMax（真实密钥只放在环境变量或 secret store，不写入仓库）
export MINIMAX_API_KEY=replace-with-your-key
export MINIMAX_MODEL=MiniMax-M3
export MINIMAX_BASE_URL=https://api.minimaxi.com   # 国际站可用 https://api.minimax.io
export MINIMAX_PROTOCOL=minimax                    # 或 openai（/v1/chat/completions）

# PowerContext（默认 http://127.0.0.1:8000）
export POWERCONTEXT_URL=http://127.0.0.1:8000
export POWERCONTEXT_STATE_BACKEND=powercontext   # 离线可设 local
# export POWERCONTEXT_SCOPE=<已有 scope_id>; 未设置时模块自动创建并缓存到 .data/scope.json
# export POWERCONTEXT_TOKEN=<启用鉴权时填写>
```

启动本地 PowerContext Server（保持终端不关）：

```bash
# 方式一：默认本地 SQLite，无需模型凭据，显式 Memory 可用
powercontext server run --role all --host 127.0.0.1 --port 8000

# 方式二：使用配置向导生成的环境文件
powercontext config init --output .env
powercontext server run --env-file .env
```

`curl --fail --silent http://127.0.0.1:8000/health/live` 可确认存活。模块通过 `POST /v1/scopes` 创建/复用 Scope，通过 `POST /v1/memory/remember` 写入状态、`POST /v1/memory/search` 读取状态。首次运行会把 `scope_id` 缓存到 `.data/scope.json`，后续进程直接复用。

### 在 Windows + WSL2 上运行（可选）

WSL2 是完整的 Linux 内核，可以直接跑 seekdb 与 PowerContext Server。注意把工程复制到 WSL 文件系统，不要直接在 `/mnt/c` 下跑 seekdb。

```bash
# 1) WSL 内一次性准备（以 Ubuntu 24.04、root 为例）
apt-get update && apt-get install -y python3-venv python3-pip
python3 -m venv ~/sddrun/venv && . ~/sddrun/venv/bin/activate
pip install -r /mnt/c/path/to/minimax/requirements.txt

# 2) 复制工程到 ext4 再运行
cp -a /mnt/c/path/to/minimax ~/sddctx && cd ~/sddctx
rm -rf .data .work

# 3) 终端 A：启动 Server
powercontext server run --role all --host 127.0.0.1 --port 8000

# 4) 终端 B：真实 MiniMax 验收
export MINIMAX_API_KEY=... MINIMAX_MODEL=MiniMax-M3 MINIMAX_BASE_URL=https://api.minimaxi.com
make clean && make demo
```

WSL 内的客户端访问 `127.0.0.1:8000` 即可；若要在 Windows 上用浏览器看 `/docs`，Windows 11 的 WSL2 默认会把 localhost 转发到 WSL，直接打开 `http://127.0.0.1:8000/docs` 即可。

## 4. 调用入口

CLI 统一入口 `python -m sddctx <command>`，输入为任务文本，输出为上下文（JSON/文本）或开发记录。

```bash
# 索引工程资料（规格/代码/测试 → seekdb）
python -m sddctx ingest

# 构建上下文（摘要；--write 落盘 artifacts/context.{json,md}；--resume 注入已保存的任务进展）
python -m sddctx context --task "为 list_tasks 增加按 status 筛选" --write

# 只让 MiniMax 改代码（不写状态）
python -m sddctx run-agent

# 在临时工作副本上运行测试
python -m sddctx test all

# 读取已保存的任务状态（stdout 只输出 JSON）
python -m sddctx state-load

# 一键端到端验收（推荐）
python -m sddctx demo
```

`demo` 依次执行 12 项检查：清空产物 → 入库 → 构建上下文 → 修改前目标测试失败 → MiniMax 修改 → 目标测试通过 → 回归测试通过 → 写开发记录 → 保存状态 → **新进程**读取状态 → 用状态构建下一个任务上下文 → 规格变更后重新入库并检索到新规格。

## 5. 验证样例

详见 [docs/sample-task.md](docs/sample-task.md)。核心验收点：

- 上下文必须包含 `specs/taskboard.md` 的 `REQ-003`、`src/taskboard/service.py` 的 `list_tasks`、`tests/test_target_filter.py` 的两个测试；
- 修改前 `tests/test_target_filter.py` 因功能缺失失败（`2 failed`），修改后通过（`2 passed`）；
- `tests/test_regression.py` 始终通过（`5 passed`）；
- 规格更新（新增 REQ-005）后重新入库，检索结果切换为更新后的内容。

## 6. 运行产物（技术使用记录）

| 产物 | 内容 |
| --- | --- |
| `artifacts/report.json` | 全部检查项、耗时、各阶段结果 |
| `artifacts/context.json` / `.md` | 本次任务的上下文与来源 |
| `artifacts/context_evolved.json` | 规格演进后重新检索的结果 |
| `artifacts/context_resume.md` | 注入已保存状态后的下一个任务上下文 |
| `artifacts/prompts/attempt*.json` | 实际发送给 MiniMax 的完整提示词 |
| `artifacts/dev_record.json` | MiniMax 开发记录：任务、上下文来源、尝试、差异、测试结果（与 `diff.patch` 对应） |
| `artifacts/diff.patch` | 模型产出的代码差异 |
| `artifacts/service_before.py` / `service_after.py` | 修改前后代码快照 |
| `artifacts/test_logs/*.log` | 命令、退出码、代码版本、pytest 输出 |
| `artifacts/db_queries.log` | 每条 SQL、参数、返回行数、数据库名 |
| `artifacts/state_ops.log` | PowerContext 状态写入/读取记录 |

## 7. 验证状态

| 环境 | 数据库 | 模型 | 状态复用 | 结果 |
| --- | --- | --- | --- | --- |
| Windows 11 + Python 3.13 | sqlite（联调） | `stub` 回放 | PowerContext 1.4.1 HTTP | 12/12 |
| WSL2 Ubuntu 24.04 + Python 3.12 | **seekdb 1.4.0** | `stub` 回放 | PowerContext 1.4.1 HTTP | 12/12，`artifacts/` 即本次运行产物 |
| Linux + 真实密钥 | seekdb | **MiniMax-M3** | PowerContext 1.4.1 HTTP | 提交前需执行一次 |

`artifacts/dev_record.json` 的 `live_minimax` 字段会标记模型是否真实调用；提交前应为 `true`。

## 8. 已知限制

- seekdb 仅支持 Linux；Windows 本地联调需 `SDDCTX_DB_BACKEND=sqlite`。仓库内 `artifacts/` 已由 WSL2 + seekdb 生成，但模型仍是 `stub` 回放；提交前请用真实 MiniMax 密钥在 Linux/WSL 上执行一次 `make clean && make demo` 覆盖。
- 检索是 SQL `LIKE` + 关键词命中计数的轻量实现，不依赖 embedding；任务描述过短时召回质量会下降。
- 代码修改为单文件 unified diff，最多重试 3 轮；不处理跨文件重构。
- 离线 `SDDCTX_PROVIDER=stub` 会回放 `sddctx/golden_patch.diff`，仅用于流水线冒烟测试，不替代 MiniMax 的真实生成。
- 一个 Scope 对应一个项目；状态记录以 `updated_at` 取最新，不保留完整历史版本链。
