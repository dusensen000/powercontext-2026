export interface Chunk {
  id: string;
  docId: string;
  title: string;
  index: number;
  text: string;
}

export interface SearchHit {
  id: string;
  text: string;
  metadata: { docId?: string; title?: string; index?: number };
  distance: number | null;
}

export interface DocumentInput {
  id: string;
  text: string;
  metadata: Record<string, string | number>;
}

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || `${response.status} ${response.statusText}`);
  }
  return body as T;
}

export const api = {
  health: () =>
    request<{ ok: boolean; collections: number; seekdb: Record<string, unknown>; vectorDimension: number }>(
      "/health",
    ),
  ensure: (kbId: string) =>
    request<{ name: string; count: number }>(`/kb/${encodeURIComponent(kbId)}/ensure`, { method: "POST" }),
  stats: (kbId: string) =>
    request<{ name: string; count: number }>(`/kb/${encodeURIComponent(kbId)}/stats`),
  addDocuments: (kbId: string, documents: DocumentInput[], embeddings: number[][]) =>
    request<{ upserted: number; count: number; upsertMs: number; refreshMs: number }>(
      `/kb/${encodeURIComponent(kbId)}/documents`,
      {
        method: "POST",
        body: JSON.stringify({ documents, embeddings, refresh: true }),
      },
    ),
  search: (kbId: string, query: string, embedding: number[], nResults = 8) =>
    request<{ mode: string; results: SearchHit[]; dbMs: number }>(
      `/kb/${encodeURIComponent(kbId)}/search`,
      {
        method: "POST",
        body: JSON.stringify({ query, embedding, nResults, mode: "hybrid" }),
      },
    ),
  removeKb: (kbId: string) =>
    request<{ deleted: string }>(`/kb/${encodeURIComponent(kbId)}`, { method: "DELETE" }),
};
