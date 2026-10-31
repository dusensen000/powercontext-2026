import express from "express";
import {
  SeekdbClient,
  Schema,
  VectorIndexConfig,
  FulltextIndexConfig,
} from "seekdb";

const PORT = Number(process.env.PORT || 8787);
const VECTOR_DIM = 384;
const BATCH_SIZE = 32;

const connection = {
  host: process.env.SEEKDB_HOST || "127.0.0.1",
  port: Number(process.env.SEEKDB_PORT || 2881),
  user: process.env.SEEKDB_USER || "root",
  password: process.env.SEEKDB_PASSWORD || "",
  database: process.env.SEEKDB_DATABASE || "test",
};

const client = new SeekdbClient(connection);
const collections = new Map();

const app = express();
app.use(express.json({ limit: "128mb" }));
app.use((req, res, next) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") {
    res.sendStatus(204);
    return;
  }
  next();
});

function collectionName(kbId) {
  const safe = String(kbId || "default")
    .toLowerCase()
    .replace(/[^a-z0-9_]/g, "_")
    .slice(0, 48);
  return `stepfun_kb_${safe}`;
}

function createSchema() {
  return new Schema({
    fulltextIndex: new FulltextIndexConfig("ngram", { ngram_token_size: 3 }),
    vectorIndex: new VectorIndexConfig({
      hnsw: { dimension: VECTOR_DIM, distance: "cosine" },
      embeddingFunction: null,
    }),
  });
}

async function getCollection(kbId) {
  const name = collectionName(kbId);
  let collection = collections.get(name);
  if (collection) return collection;
  if (await client.hasCollection(name)) {
    collection = await client.getCollection({ name });
  } else {
    collection = await client.createCollection({ name, schema: createSchema() });
  }
  collections.set(name, collection);
  return collection;
}

function wrap(handler) {
  return (req, res, next) => {
    Promise.resolve(handler(req, res, next)).catch((error) => {
      console.error(error);
      res.status(500).json({ error: String(error?.message || error) });
    });
  };
}

app.get(
  "/api/health",
  wrap(async (_req, res) => {
    const collectionCount = await client.countCollection();
    res.json({
      ok: true,
      seekdb: connection,
      collections: collectionCount,
      vectorDimension: VECTOR_DIM,
    });
  }),
);

app.post(
  "/api/kb/:kbId/ensure",
  wrap(async (req, res) => {
    const collection = await getCollection(req.params.kbId);
    const count = await collection.count();
    res.json({ name: collectionName(req.params.kbId), count });
  }),
);

app.post(
  "/api/kb/:kbId/documents",
  wrap(async (req, res) => {
    const { documents, embeddings, refresh = true } = req.body || {};
    if (!Array.isArray(documents) || !Array.isArray(embeddings)) {
      res.status(400).json({ error: "documents and embeddings are required" });
      return;
    }
    if (documents.length !== embeddings.length) {
      res.status(400).json({ error: "documents and embeddings length mismatch" });
      return;
    }
    const collection = await getCollection(req.params.kbId);
    const upsertStart = performance.now();
    for (let offset = 0; offset < documents.length; offset += BATCH_SIZE) {
      const slice = documents.slice(offset, offset + BATCH_SIZE);
      const vectors = embeddings.slice(offset, offset + BATCH_SIZE);
      for (const vector of vectors) {
        if (!Array.isArray(vector) || vector.length !== VECTOR_DIM) {
          res.status(400).json({ error: `embedding dimension must be ${VECTOR_DIM}` });
          return;
        }
      }
      await collection.upsert({
        ids: slice.map((doc) => String(doc.id)),
        documents: slice.map((doc) => String(doc.text)),
        metadatas: slice.map((doc) => doc.metadata || {}),
        embeddings: vectors,
      });
    }
    const upsertMs = performance.now() - upsertStart;
    let refreshMs = 0;
    if (refresh) {
      const refreshStart = performance.now();
      await collection.refresh_index();
      refreshMs = performance.now() - refreshStart;
    }
    const count = await collection.count();
    res.json({
      upserted: documents.length,
      count,
      upsertMs: Math.round(upsertMs * 10) / 10,
      refreshMs: Math.round(refreshMs * 10) / 10,
    });
  }),
);

function firstRow(result) {
  const pick = (value) => (Array.isArray(value?.[0]) ? value[0] : value || []);
  return {
    ids: pick(result?.ids),
    distances: pick(result?.distances),
    documents: pick(result?.documents),
    metadatas: pick(result?.metadatas),
  };
}

app.post(
  "/api/kb/:kbId/search",
  wrap(async (req, res) => {
    const { query = "", embedding, nResults = 8, mode = "hybrid" } = req.body || {};
    if (!Array.isArray(embedding) || embedding.length !== VECTOR_DIM) {
      res.status(400).json({ error: `embedding must have ${VECTOR_DIM} values` });
      return;
    }
    const collection = await getCollection(req.params.kbId);
    const start = performance.now();
    let raw;
    const include = ["documents", "metadatas", "distances"];
    if (mode === "vector" || !String(query).trim()) {
      raw = await collection.query({
        queryEmbeddings: [embedding],
        nResults,
        include,
      });
    } else if (mode === "fulltext") {
      raw = await collection.hybridSearch({
        query: { whereDocument: { $contains: String(query) } },
        nResults,
        include,
      });
    } else {
      raw = await collection.hybridSearch({
        query: { whereDocument: { $contains: String(query) } },
        knn: { queryEmbeddings: [embedding] },
        nResults,
        include,
      });
    }
    const dbMs = performance.now() - start;
    const rows = firstRow(raw);
    const results = rows.ids.map((id, index) => ({
      id: String(id),
      text: rows.documents[index] || "",
      metadata: rows.metadatas[index] || {},
      distance: rows.distances[index] ?? null,
    }));
    res.json({ mode, results, dbMs: Math.round(dbMs * 10) / 10 });
  }),
);

app.get(
  "/api/kb/:kbId/stats",
  wrap(async (req, res) => {
    const collection = await getCollection(req.params.kbId);
    res.json({ name: collectionName(req.params.kbId), count: await collection.count() });
  }),
);

app.delete(
  "/api/kb/:kbId",
  wrap(async (req, res) => {
    const name = collectionName(req.params.kbId);
    collections.delete(name);
    if (await client.hasCollection(name)) await client.deleteCollection(name);
    res.json({ deleted: name });
  }),
);

app.listen(PORT, "127.0.0.1", () => {
  console.log(`stepfun seekdb API listening on http://127.0.0.1:${PORT}`);
  console.log(`seekdb target: ${connection.host}:${connection.port}/${connection.database}`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    try {
      await client.close();
    } finally {
      process.exit(0);
    }
  });
}
