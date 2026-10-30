---
title: Exact input encoding
description: Configure reversible stage input encoding and keep local estimates separate from provider usage.
---

# Exact input encoding

`InferenceConfig.input_encoding` selects input representation by operation; unspecified operations default to `off`.
The supported operations are `atomic_memory.extract`, `atomic_memory.reconcile`, `experience.generate`, and
`experience.incubate`. Unknown or unintegrated operations fail configuration validation. Experience generation and
incubation are independent. Skill, Profile, Handoff, and Topic Memory are not integrated with this encoding strategy.

```python
InferenceConfig(input_encoding={
    "atomic_memory.extract": "shadow",
    "experience.generate": "shadow",
    "experience.incubate": "off",
})
```

The Server accepts a JSON environment variable:

```bash
POWERCONTEXT_SERVER_INFERENCE_INPUT_ENCODING='{"experience.generate":"shadow"}'
```

The existing `atomic_memory_input_encoding` setting and
`POWERCONTEXT_SERVER_INFERENCE_ATOMIC_MEMORY_INPUT_ENCODING` variable remain the fallback for the two Atomic Memory
operations. Explicit operation settings take precedence, including explicit `off`. Serialized worker configuration
preserves the same selection. Encoding changes neither Sources, Artifacts, PreparedContext, nor embedding inputs,
and adds no auxiliary model calls.

| Mode | Input sent to the model | Local diagnostics |
| --- | --- | --- |
| `off` | Original compact JSON | No candidate construction |
| `shadow` | Original compact JSON | Candidate construction, restoration checks, and cost estimates |
| `active` | Eligible smaller candidate, otherwise original | Selection or fallback reason |

`active` is experimental and needs acceptance for the target model and instruction combination. Exact JSON
reconstruction does not establish equivalent model understanding or cheaper reasoning. Actual usage can increase,
and output-budget exhaustion can prevent delivery. Observe representative inputs in `shadow`, then explicitly run
a real A/B comparison of required facts, citations, failures, and complete input plus output usage before enabling
the strategy for that deployment.
Accept every operation separately; Atomic Memory extraction results do not validate reconciliation or Experience generation.

The first codec, `shared-json-v1`, stores identical long text, metadata, or structural values once and retains
a reference at every occurrence in the ordered original tree. Project metadata often repeats in the body
projection, Source metadata, and multiple Sources. Sharing a value never merges Source identities, times,
journal positions, citations, order, or repeated occurrences. Typed object, array, and reference nodes keep
user-provided `$ref` fields distinct from internal references.

Atomic Memory retains compatible `shared-json-v1`. Experience uses `shared-json-v2`, which also recognizes
canonical JSON embedded in content strings and identical text fragments including their original line terminators.
Repeated content under distinct Source identities can be shared while retaining each identity, fragment order, and
occurrence. Noncanonical JSON strings are never reformatted. Full-envelope savings and reconstruction checks still
decide eligibility; public inputs without suitable repetition retain their original representation.

Every eligible candidate must restore the **exact original stage JSON string**, including key order, Unicode,
code, whitespace inside strings, nulls, booleans, and `1` versus `1.0`. The same estimator counts decoding
instructions, shared values, and references. Selection requires fewer bytes and savings of at least 32 estimated
tokens and at least 5%. Fewer bytes or estimated tokens do not guarantee fewer provider tokens.
Input bytes, depth, nodes, shared entries, and expanded decoding all have limits. Unsupported or oversized inputs
retain their original representation. Custom Artifact Prompts also retain the original field contract.

Atomic Memory stage budgeting and generation use the same representation selection. Experience retains its existing
evidence count/length and request limits; the executor still checks the complete request against the target window.
This configuration does not introduce an Experience-specific stage token budget. Enforced privacy protection checks the
original serialization and strictly decoded content first, including nested JSON objects and arrays inside strings.
Candidate JSON parsing/depth or size limits may cause fallback to the original representation that passed this check.
Detected forbidden content, duplicate JSON keys, and other policy failures reject the invocation; these failures
cannot become representation fallback.
This content check never grants full request admission: final privacy and target-window checks still inspect
the complete model request. Fallback never authorizes an unsafe or over-budget original request.
The codec does not remove successful log entries, truncate code, merge distinct log events by template, or write
encoded input back into authoritative records.

For in-process inspection, wrap a call with
`powercontext.builtin.inference.usage.collect_input_encodings()`.
It collects at most 128 content-free reports: stage, codec, mode, selection/fallback reason, original/candidate/
selected bytes and estimated tokens, estimator version, shared values, and references. Budget probes do not
duplicate reports. `UsageReportingStructuredGenerator` attaches the actual preparation reports to the same call's
`InferenceUsage.input_encodings` and sends them through the existing bound usage reporter. Successful results and
failures carrying known usage retain this association. Estimates remain separate from provider `input_tokens` and
`output_tokens`; never add them together or substitute one for the other. Failures without usage stay unknown and
do not create a zero-request billing record. An original-input privacy rejection precedes encoding and produces
no encoding report. The explicit diagnostic collector still works around the call.
These diagnostics belong to the current process and invocation context; they do not aggregate across workers.
Existing persistent statistics aggregate actual model usage only and do not store encoding details or provide a
complete billing ledger. Evaluate repeated metadata, equal bodies with distinct identities, unique short inputs,
and multilingual code/JSON separately.
