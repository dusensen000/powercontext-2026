---
title: 精确输入编码
description: 按操作配置可逆输入编码，并区分本地估算与供应商实际用量。
---

# 精确输入编码

`InferenceConfig.input_encoding` 按操作选择输入表示，未指定的操作默认 `off`。当前接入
`atomic_memory.extract`、`atomic_memory.reconcile`、`experience.generate` 和 `experience.incubate`；
未知或尚未接入的操作会在配置加载时拒绝。Experience 生成与孵化分别控制，Skill、Profile、Handoff、
Topic Memory 尚未接入本编码策略。

```python
InferenceConfig(input_encoding={
    "atomic_memory.extract": "shadow",
    "experience.generate": "shadow",
    "experience.incubate": "off",
})
```

Server 可通过 JSON 环境变量配置：

```bash
POWERCONTEXT_SERVER_INFERENCE_INPUT_ENCODING='{"experience.generate":"shadow"}'
```

旧的 `atomic_memory_input_encoding` 配置及
`POWERCONTEXT_SERVER_INFERENCE_ATOMIC_MEMORY_INPUT_ENCODING` 环境变量继续作为两个 Atomic Memory 操作的默认值；
显式操作配置优先，包括显式 `off`。配置序列化后，后台 worker 使用相同选择规则。
编码不修改 Source、Artifact、PreparedContext 或 Embedding 输入，也不增加辅助模型调用。

| 模式 | 发给模型的内容 | 本地诊断 |
| --- | --- | --- |
| `off` | 原来的紧凑 JSON | 不构造候选 |
| `shadow` | 原来的紧凑 JSON | 计算候选、还原校验和成本 |
| `active` | 合格且更小的候选，否则原文 | 记录采用或回退原因 |

`active` 是需要按目标模型和指令组合验收的试验能力。程序能够完整还原 JSON，不等于模型阅读编码后
质量不变或推理更便宜；真实用量可能增加，也可能因输出预算耗尽而无法交付。先用 `shadow` 观察代表性输入，
再显式运行真实 A/B，确认必需事实、引用、失败率及输入加输出的完整用量后，才考虑为对应部署启用。
每个操作需要独立验收；Atomic Memory 提取的结果不代表调和或 Experience 生成的质量。

首个 codec `shared-json-v1` 将严格相同的长正文、metadata 或结构值保存一次，在有序原树的每个出现位置保留引用。
例如同一个项目的 metadata 同时出现在正文投影、来源元信息和多条 Source 中，只共享值，不合并 Source。
不同记录的身份、时间、journal position、引用、顺序和重复出现仍然全部保留。
原树使用带类型的对象、数组和引用节点，用户自己的 `$ref` 字段不会被当作内部引用。

Atomic Memory 使用兼容的 `shared-json-v1`。Experience 的 `shared-json-v2` 进一步支持正文字符串内部的
规范 JSON，以及保留原始换行符的完全相同文本片段。它能处理不同 Source 身份包裹的重复内容，
同时保留每条 Source 的身份、片段顺序和出现次数。非规范 JSON 字符串不被重新格式化。
候选是否采用仍取决于完整表示的收益与还原检查；公共数据中没有合适重复时继续使用原文。

每次候选都必须还原成与原始阶段 JSON **完全相同的字符串**，包括键顺序、Unicode、代码、空白字符串、
`null`、布尔值、`1` 与 `1.0`。解码说明、值表和引用开销都计入相同的估算器；只有字节更少且
至少减少 32 个估算 Token、同时减少至少 5% 才能采用。字节或估算变小不保证供应商实际 Token 下降。
输入大小、深度、节点数、共享值数量和解码展开均有上限，超限或不支持时保留原表示。
未知自定义 Artifact Prompt 使用原表示，避免改变它依赖的输入字段契约。

Atomic Memory 的阶段预算和生成器使用相同的表示选择。Experience 保留原有证据数量/长度与请求限制，
完整模型请求仍由执行侧检查目标窗口；本配置不新增 Experience 专属阶段预算。
启用强制隐私保护时，先检查原始序列化文本及严格解码后的内容，包括字符串内嵌的 JSON 对象和数组。
候选遇到 JSON 解析、深度或大小限制时，可以回退到已经通过检查的原文。
发现禁止内容、重复 JSON 键或其他策略失败时拒绝调用，不能将这些失败转为表示回退。
这项内容检查不授予完整请求的放行资格，最终完整模型请求仍经过隐私和目标窗口检查；
回原文不构成放行，原文不安全或仍超预算时继续拒绝。
这里没有删除成功日志、截断代码、按模板合并不同日志，也不把压缩过的输入写回权威记录。

进程内可使用
`powercontext.builtin.inference.usage.collect_input_encodings()`
包围一次调用，读取最多 128 条无正文诊断。记录包含阶段、codec、模式、采用/回退原因、
原始/候选/实际选择的字节和估算 Token、估算器版本、共享值与引用次数；预算探测不重复记录。
`UsageReportingStructuredGenerator` 会把本次实际准备的报告附在同一次 `InferenceUsage.input_encodings` 中，
通过现有绑定的用量 reporter 归因；返回结果和带有已知 usage 的失败都保留这份关联。
其中的估算值与供应商报告的 `input_tokens` / `output_tokens` 分开，不能相加或互相替代。
未取得 usage 的失败仍保留未知，不生成零请求的计费记录；原始隐私预检阻断发生在编码前，不生成编码报告。
显式诊断收集器仍可在调用外使用，预算探测不会计入实际调用。
这些诊断只属于当前进程和调用上下文，不自动跨 worker 汇总。现有持久统计只汇总实际模型用量，
不存储编码明细，也不是完整费用账本。
评估时应分别覆盖重复 metadata、相同正文不同身份、短小唯一输入、中英混合及代码/JSON。
