export function dedupeDocIds(ids: string[]): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const id of ids) {
    if (!seen.has(id)) {
      seen.add(id);
      ordered.push(id);
    }
  }
  return ordered;
}

export function recallAtK(rankedDocIds: string[], goldDocId: string, k: number): number {
  return dedupeDocIds(rankedDocIds).slice(0, k).includes(goldDocId) ? 1 : 0;
}

export function ndcgAtK(rankedDocIds: string[], goldDocId: string, k: number): number {
  const unique = dedupeDocIds(rankedDocIds);
  const rank = unique.slice(0, k).indexOf(goldDocId);
  if (rank < 0) return 0;
  return 1 / Math.log2(rank + 2);
}

export function mean(values: number[]): number {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

export function median(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function percentile(values: number[], p: number): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[index];
}
