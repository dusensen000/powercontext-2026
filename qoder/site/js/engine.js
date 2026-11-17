/**
 * Relay 站内引擎：中文分词、TF-IDF 向量、余弦距离、RRF 融合、纪要规则抽取。
 * 纯前端实现，不依赖任何外部服务。
 */

export const KINDS = ["decision", "action", "risk", "question"];
export const KIND_LABEL = { decision: "决定", action: "行动项", risk: "风险", question: "待确认" };
export const STATUSES = ["open", "in_progress", "blocked", "done", "stale"];
export const STATUS_LABEL = { open: "待办", in_progress: "进行中", blocked: "受阻", done: "已完成", stale: "搁置" };
export const OPEN_STATUSES = ["open", "in_progress", "blocked"];

const STOP_CHARS = new Set("的了在和与及或就都也很还有是不对把被将由从一这个我们你们他们".split(""));

/** 字符二元组 + 英文/数字词，够短、对中文短句足够稳。 */
export function tokenize(text) {
  const out = [];
  const normalized = String(text || "")
    .toLowerCase()
    .replace(/[\s\u3000]+/g, " ")
    .trim();
  if (!normalized) return out;

  for (const word of normalized.match(/[a-z0-9][a-z0-9._-]*/g) || []) out.push(word);

  const cjk = normalized.replace(/[^\u4e00-\u9fa5]+/g, " ");
  for (const chunk of cjk.split(" ")) {
    if (!chunk) continue;
    if (chunk.length === 1) { out.push(chunk); continue; }
    for (let i = 0; i < chunk.length - 1; i++) {
      const gram = chunk.slice(i, i + 2);
      if (STOP_CHARS.has(gram[0]) && STOP_CHARS.has(gram[1])) continue;
      out.push(gram);
    }
  }
  return out;
}

export class Vectorizer {
  constructor(documents) {
    this.idf = new Map();
    this.fit(documents);
  }

  fit(documents) {
    const df = new Map();
    for (const doc of documents) {
      for (const token of new Set(tokenize(doc))) df.set(token, (df.get(token) || 0) + 1);
    }
    const total = Math.max(documents.length, 1);
    this.idf = new Map();
    for (const [token, count] of df) {
      this.idf.set(token, Math.log((1 + total) / (1 + count)) + 1);
    }
  }

  vector(text) {
    const counts = new Map();
    for (const token of tokenize(text)) counts.set(token, (counts.get(token) || 0) + 1);
    const vec = new Map();
    let norm = 0;
    for (const [token, count] of counts) {
      const weight = (1 + Math.log(count)) * (this.idf.get(token) || Math.log(2));
      vec.set(token, weight);
      norm += weight * weight;
    }
    norm = Math.sqrt(norm) || 1;
    for (const [token, weight] of vec) vec.set(token, weight / norm);
    return vec;
  }
}

export function cosine(a, b) {
  if (!a || !b || !a.size || !b.size) return 0;
  const [small, large] = a.size <= b.size ? [a, b] : [b, a];
  let dot = 0;
  for (const [token, weight] of small) {
    const other = large.get(token);
    if (other) dot += weight * other;
  }
  return Math.max(0, Math.min(1, dot));
}

export const distance = (a, b) => 1 - cosine(a, b);

/** Reciprocal Rank Fusion：先各自排序，再按 1/(k+rank) 相加。 */
export function rrf(rankings, k = 60) {
  const fused = new Map();
  rankings.forEach((ranking) => {
    ranking.forEach((id, index) => {
      fused.set(id, (fused.get(id) || 0) + 1 / (k + index + 1));
    });
  });
  return [...fused.entries()]
    .map(([id, score]) => ({ id, score }))
    .sort((a, b) => b.score - a.score);
}

/* ------------------------------------------------------------------ */
/* 纪要抽取：规则引擎                                                   */
/* ------------------------------------------------------------------ */

const KIND_HINTS = [
  ["risk", /风险|可能导致|容易|不一致|打满|超时|阻塞|丢失|误操作|隐患/],
  ["question", /待确认|是否|要不要|多少|回滚阈值|结论|建议/],
  ["decision", /决定|方案|约束|策略|采用|推迟|不下线|扩大到|保持不变|不能下线|暂不/],
  ["action", /负责|需要|给出|交付|输出|完成|编写|联系|跑完|推进|调整|排期/],
];

const STATUS_HINTS = [
  ["done", /已确认|已完成|已交付|已通过|通过评审|已上线|不再/],
  ["in_progress", /80%|还没开始|进行中|推进中|观察中|已放/],
  ["blocked", /受阻|阻塞|卡住|还没排期|没有排期/],
];

const NOISE = [
  /^#+\s*/,
  /^时间[:：]/,
  /^参与[:：]/,
  /^背景$/,
  /^讨论记录$/,
  /^进展$/,
  /^新增$/,
  /^当前状态$/,
  /^[-—=]{2,}$/,
];

/** 纯叙述、不是可交代的事项，抽出来只会污染台账。 */
const NARRATIVE = /调去|转岗|借调|离开项目|加入项目/;

const DEFAULT_NAMES = ["张伟", "李静", "王强", "赵磊", "陈曦"];

function stripNumber(line) {
  return line.replace(/^\s*(?:[-*·]|\(?\d{1,2}[.、)）]|[一二三四五六七八九十]+[、.])\s*/, "").trim();
}

function parseYear(text) {
  const match = text.match(/(20\d{2})\s*[-/年]/);
  return match ? Number(match[1]) : new Date().getFullYear();
}

function monthLength(year, month) {
  return new Date(year, month, 0).getDate();
}

function parseDue(text, year) {
  let match = text.match(/(\d{1,2})\s*月\s*(\d{1,2})\s*日/);
  if (match) {
    const m = Number(match[1]);
    const d = Number(match[2]);
    return `${year}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  }
  match = text.match(/(\d{1,2})\s*月底/);
  if (match) {
    const m = Number(match[1]);
    return `${year}-${String(m).padStart(2, "0")}-${String(monthLength(year, m)).padStart(2, "0")}`;
  }
  match = text.match(/(20\d{2})-(\d{1,2})-(\d{1,2})/);
  if (match) return `${match[1]}-${match[2].padStart(2, "0")}-${match[3].padStart(2, "0")}`;
  return "";
}

function collectNames(text) {
  const names = new Set(DEFAULT_NAMES);
  const header = text.match(/^参与[:：].*$/m);
  if (header) {
    for (const part of header[0].replace(/^参与[:：]/, "").split(/[、,，\s]+/)) {
      const name = part.replace(/[（(].*$/, "").trim();
      if (/^[\u4e00-\u9fa5]{2,3}$/.test(name)) names.add(name);
    }
  }
  return names;
}

function detectOwner(text, names) {
  for (const name of names) {
    if (text.includes(name)) {
      // 出现在“参与：”里的名字不算负责人
      if (/^参与[:：]/.test(text.trim())) continue;
      return name;
    }
  }
  return "";
}

function kindOf(text) {
  for (const [kind, pattern] of KIND_HINTS) if (pattern.test(text)) return kind;
  return "action";
}

function statusOf(text) {
  if (/已确认|已完成|已交付|已通过|通过评审|不再|保持不变|约束不变/.test(text)) return "done";
  for (const [status, pattern] of STATUS_HINTS) if (pattern.test(text)) return status;
  return "open";
}

function cleanTitle(text, owner, names) {
  let title = text
    .replace(/^[^：:]{2,4}[：:]\s*/, "")                        // 去掉 “风险：”“待确认：”
    .replace(/^(现状|目标|方案|约束|风险|待确认|决定|已完成|未完成)[:：]\s*/, "")
    .replace(/^[\u4e00-\u9fa5]{2,3}[：:]\s*/, "")              // 去掉 “张伟：”
    .trim();

  for (const name of names) {
    title = title.replace(new RegExp(`^${name}(负责|需要|在|会|将|本周)?的?`), "");
  }
  title = title
    .replace(/^\s*(在|由)?\s*/, "")
    .replace(/^(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(前|之前)/, "")
    .replace(/^(\d{1,2})\s*月底\s*(前|之前)/, "")
    .replace(/^原定\s*/, "")
    .replace(/[。；;]\s*$/, "")
    .trim();

  if (title.length > 30) {
    const clauses = title.split(/(?<=[，,；;])/).map((part) => part.replace(/[，,；;]$/, ""));
    let built = "";
    for (const clause of clauses) {
      const next = built ? `${built}，${clause}` : clause;
      if (next.length > 30) break;
      built = next;
    }
    title = built || clauses[0].slice(0, 30);
  }
  return title
    .replace(/\s+(?=[，,。；;]|$)/g, "")
    .replace(/\s*等$/, " 等")
    .trim() || text.slice(0, 30);
}

/**
 * 从一份纪要里抽条目。规则版：不调用模型，输入输出确定，
 * 适合在没有密钥的浏览器里复现整条链路。
 */
export function extractMeeting(text, options = {}) {
  const year = options.year || parseYear(text);
  const names = collectNames(text);
  const lines = String(text || "").split(/\r?\n/);
  const items = [];
  const seen = new Set();

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;
    if (NOISE.some((pattern) => pattern.test(line))) continue;
    if (/^##\s*(讨论记录|进展|新增|当前状态|背景)/.test(line)) continue;

    for (const piece of line.split(/(?<=[。；;])/)) {
      let segment = stripNumber(piece).replace(/^##\s*/, "").trim();
      if (!segment || segment.length < 6) continue;
      if (NARRATIVE.test(segment) && !/风险|待确认|负责/.test(segment)) continue;

      // “已完成：a、b、c” 这类合写，拆成一条，标题用前缀概括
      const labelMatch = segment.match(/^(现状|目标|方案|约束|风险|待确认|决定|已完成|未完成)[:：]/);
      if (labelMatch && /、/.test(segment)) {
        const label = labelMatch[1];
        const rest = segment.slice(labelMatch[0].length);
        const parts = rest.split(/[、,，]/).map((p) => p.trim()).filter(Boolean);
        if (parts.length > 1) {
          const title = `${label}：${parts.slice(0, 2).join("、")}${parts.length > 2 ? " 等" : ""}`;
          const key = title.replace(/\s/g, "");
          if (!seen.has(key)) {
            seen.add(key);
            items.push({
              kind: kindOf(segment),
              title: title.slice(0, 34),
              detail: segment.replace(/[。；;]$/, ""),
              owner: detectOwner(segment, names),
              due: parseDue(segment, year),
              status: statusOf(segment),
            });
          }
          continue;
        }
      }

      const title = cleanTitle(segment, detectOwner(segment, names), names);
      const key = title.replace(/[\s，,。；;]/g, "");
      if (!key || seen.has(key)) continue;
      seen.add(key);

      items.push({
        kind: kindOf(segment),
        title,
        detail: segment.replace(/[。；;]$/, ""),
        owner: detectOwner(segment, names),
        due: parseDue(segment, year),
        status: statusOf(segment),
      });
    }
  }
  return items.slice(0, 24);
}

/* ------------------------------------------------------------------ */
/* 去重与检索                                                          */
/* ------------------------------------------------------------------ */

export function buildIndex(items) {
  const docs = items.map((item) => `${item.title}\n${item.detail || ""}`);
  const vectorizer = new Vectorizer(docs);
  const vectors = new Map();
  items.forEach((item, index) => vectors.set(item.id, vectorizer.vector(docs[index])));
  return { vectorizer, vectors };
}

export function judgeCandidate(vectorizer, vectors, items, candidate, threshold) {
  const text = `${candidate.title}\n${candidate.detail || ""}`;
  const vec = vectorizer.vector(text);
  let best = { id: null, title: "", distance: Infinity };
  for (const item of items) {
    const d = distance(vec, vectors.get(item.id));
    if (d < best.distance) best = { id: item.id, title: item.title, distance: d };
  }
  return {
    ...best,
    isDuplicate: best.distance <= threshold,
    vector: vec,
  };
}

export function search(store, query, keyword) {
  const items = store.items;
  const docs = items.map((item) => `${item.title}\n${item.detail || ""}`);

  const keywordRanking = keyword
    ? items
        .map((item) => ({ id: item.id, hits: countHits(`${item.title}\n${item.detail || ""}`, keyword) }))
        .filter((row) => row.hits > 0)
        .sort((a, b) => b.hits - a.hits)
        .map((row) => row.id)
    : [];

  let semanticRanking = [];
  const semanticScore = new Map();
  if (query) {
    const vectorizer = store.vectorizer;
    const qv = vectorizer.vector(query);
    const scored = items.map((item) => {
      const vec = store.vectors.get(item.id) || vectorizer.vector(docs[items.indexOf(item)]);
      const sim = cosine(qv, vec);
      semanticScore.set(item.id, sim);
      return { id: item.id, sim };
    });
    semanticRanking = scored
      .filter((row) => row.sim > 0)
      .sort((a, b) => b.sim - a.sim)
      .map((row) => row.id);
  }

  const hybrid = rrf([semanticRanking, keywordRanking]);
  return { keywordRanking, semanticRanking, semanticScore, hybrid };
}

function countHits(text, keyword) {
  if (!keyword) return 0;
  let count = 0;
  let index = text.indexOf(keyword);
  while (index !== -1 && count < 20) {
    count += 1;
    index = text.indexOf(keyword, index + keyword.length);
  }
  return count;
}
