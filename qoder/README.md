# 接力棒 Relay

把会议纪要、聊天记录、待办，变成一张**可确认、可对账、可交接**的任务台账。

2026 OceanBase 数据库大赛 · Qoder 赛道参赛项目。

作品链接：https://relay-handoff-fg3f3bh5joq.qoder.website （静态展示站，源码就是 `site/`）

四条链路的原始输出在 `evidence/`：seekdb 三路对比、真实台账检索、端到端逐条判定与交接卡、
PowerContext 建 Scope 与召回。README 和展示站里的每个数字都能在这些日志里找到对应行。
抽取由 StepFun 完成，条目数会随运行小幅浮动（这份 evidence 那次是 23 抽 → 14 条台账），
但合并/新增的判定逻辑与台账结构不变。

## 解决什么

- **进度反复确认**：同一件事在三次会议里被说了三遍，没人说得清现在到底是哪个状态。
- **交接靠嘴**：人一调走，当时的决定和约束就留在聊天记录里，接手的人只能重读。

## 核心链路

```
粘贴纪要 → StepFun 抽取（决定/行动项/风险/待确认）
        → seekdb 混合检索去重合并
        → 台账 → 对账（超期/失联）
        → PowerContext 交接卡
```

## 为什么必须是这两个产品

**seekdb** —— 判断"这条是不是上次那件事"，只靠关键词会漏（"数据库压力大" vs "连接池打满"），
只靠语义会错（精确术语匹配不上）。所以三路一起用，一次 `hybrid_search` 内 RRF 融合：

- 全文：保证"连接池""灰度"这类精确词不漏；
- 向量：保证换了说法也能命中同一件事；
- 标量过滤：保证只在同一个项目、未完成的任务里找。

**PowerContext** —— 决定和约束要活得比单次会话久，而且带版本。交接走
工作契约 → Prepared Handoff → 确认回执 → 任务结果，
下一个会话或下一个人直接从当前状态继续，不用重读全部记录。

## 环境

Windows + WSL2 (Ubuntu)。seekdb 没有 Windows 原生包，数据库跑在 WSL 里；
代码放 Windows 侧方便 Qoder 编辑，通过 `/mnt/c` 访问。

- Python 3.12（WSL 内 `~/relay-venv`）
- seekdb 嵌入式：`pyseekdb` + `pylibseekdb`（`.env` 里留了 `SEEKDB_HOST/PORT`，填了就自动切 server 模式）
- 对话模型：StepFun `step-3.5-flash`（比赛提供，无 embedding 接口）
- Embedding：本地 `BAAI/bge-small-zh-v1.5` 走 `fastembed`（ONNX，不装 torch），
  模型下载走 `hf-mirror.com`（WSL 内访问不到 huggingface.co）
- PowerContext：独立虚拟环境 `~/pc-venv`，`powercontext[cli,server]==1.4.1`，SQLite 存储

配置见 `.env.example`，复制为 `.env` 后填入 Key。

## 跑起来

```bash
# 1) WSL 里起 PowerContext Server（一次性）
python3.12 -m venv ~/pc-venv && ~/pc-venv/bin/pip install "powercontext[cli,server]==1.4.1"
mkdir -p ~/pc-run && cd ~/pc-run && ~/pc-venv/bin/powercontext config init --template -o .env <<< y
cd ~/pc-run && nohup ~/pc-venv/bin/powercontext server run > server.log 2>&1 &

# 2) Windows 侧，项目根目录
bash run.sh scripts/smoke_embed.py          # embedding 维度与距离分布
bash run.sh scripts/smoke_seekdb.py         # 验收 1：seekdb 三种检索方式对比
bash run.sh scripts/smoke_llm.py            # 验收 2：StepFun 结构化抽取
bash run.sh scripts/setup_powercontext.py   # 建 Scope、纪要落 Source、决定落 Memory、验证召回
bash run.sh scripts/demo_e2e.py --reset     # 端到端：纪要 → 去重 → 台账 → 对账 → 交接四步
bash run.sh scripts/retrieval_check.py      # 真实台账上的三路检索对比（展示站数字来源）
```

`demo_e2e.py` 会在 PowerContext 在线时补上「工作契约 → Prepared Handoff → 确认回执 → 任务结果」，
不在线就跳过，seekdb 那条链路不受影响。

## 界面

```bash
bash run.sh --ui        # http://localhost:8501
```

四个页签：录入（抽取 + 逐条判重）、台账与对账、检索验证（三路并排）、交接（交接卡 + PowerContext 四步）。

## 展示站

`site/` 是纯静态展示站（`index.html` + `styles.css` + `assets/` 四张真实运行截图），
内容全部取自上面脚本的实测输出。本地预览：

```bash
cd site && python3 -m http.server 8777 --bind 127.0.0.1
```

发布走 Qoder Sites（`prepare_site` 会生成 `.站点名称.qoder.site` 描述文件，不要手写）。

## 目录

```
backend/
  config.py     环境变量与路径
  schema.py     WorkItem 数据模型
  llm.py        StepFun 调用 + 容错 JSON 解析
  embedding.py  本地 bge，实现并注册 pyseekdb EmbeddingFunction
  dbinit.py     建库（Client 代理不暴露 admin，走 AdminClient）
  store.py      seekdb 封装：add/update/hybrid_find/semantic_find/keyword_find
  extract.py    纪要 → 结构化条目
  dedupe.py     混合检索召回 + 余弦距离复核
  ledger.py     台账、超期与失联对账
  powercontext.py PowerContext HTTP 客户端
  handoff.py    交接四步 + 人看的交接卡渲染
app.py          Streamlit 四页签界面
data/samples/   三份样例纪要（启动会 / 周会 / 交接会）
data/out/       交接卡、Scope ID、核对用的检索与召回输出
evidence/       四条链路的真实运行日志（判题用）
site/           静态展示站（作品介绍 + 技术验证 + 界面截图）
scripts/        验收与演示脚本
requirements.txt 本地链路依赖（PowerContext 另建 venv，版本见上）
run.sh          Windows 侧调用 WSL 的入口
```

## 注意

- `.env` 含 API Key，已在 `.gitignore` 中，不要提交。
- seekdb 数据目录在 WSL 的 `/home/dss/relay-data/seekdb.db`（是目录不是文件）；`--reset` 会整目录删除重建。
- `DEDUPE_THRESHOLD=0.28` 是实测值：同一件事的不同说法余弦距离 0.09–0.28，
  不同但同话题的任务 0.34 以上。默认 0.62 会把整个项目压成一条。
- seekdb 的 `hybrid_search` 返回的是 RRF 融合分，不是余弦距离，不能直接拿去比阈值；
  所以去重是「混合检索召回候选 + 本地 embedding 复核距离」两段式。
- PowerContext 未配推理模型，`memory/search` 走的是 `mode=text` 的词面召回；
  配上 embedding 后会切到语义模式。
- 接手回执 `status=accepted` 必须带 `receiver_checks`（三项都为 confirmed），这是 PowerContext 的契约要求。

