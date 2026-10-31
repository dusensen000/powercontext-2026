export interface EvalQuery {
  id: string;
  query: string;
  goldDocId: string;
}

export interface EvalDoc {
  docId: string;
  title: string;
  text: string;
}

export interface EvalSet {
  meta: Record<string, unknown>;
  queries: EvalQuery[];
  docs: EvalDoc[];
}

let cached: Promise<EvalSet> | null = null;

export function loadEvalSet(): Promise<EvalSet> {
  if (!cached) {
    cached = fetch("/eval_set.json").then((response) => {
      if (!response.ok) throw new Error("eval set missing");
      return response.json() as Promise<EvalSet>;
    });
  }
  return cached;
}
