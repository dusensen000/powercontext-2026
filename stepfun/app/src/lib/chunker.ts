import type { Chunk } from "./api";

const SENTENCE_BREAK = /(?<=[.!?。！？])\s+/;
const TARGET = 600;
const MAX = 900;

function splitSentences(text: string): string[] {
  return text
    .replace(/\s+/g, " ")
    .split(SENTENCE_BREAK)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}

export function chunkDocument(docId: string, title: string, text: string): Chunk[] {
  const sentences = splitSentences(text);
  const chunks: string[] = [];
  let current = "";
  const flush = () => {
    if (current.trim()) chunks.push(current.trim());
    current = "";
  };
  for (const sentence of sentences) {
    if (sentence.length > MAX) {
      flush();
      for (let offset = 0; offset < sentence.length; offset += TARGET) {
        chunks.push(sentence.slice(offset, offset + TARGET));
      }
      continue;
    }
    if (current.length + sentence.length + 1 > MAX) flush();
    current = current ? `${current} ${sentence}` : sentence;
    if (current.length >= TARGET) flush();
  }
  flush();
  return chunks.map((text, index) => ({
    id: `${docId}::${index}`,
    docId,
    title,
    index,
    text,
  }));
}

export function chunkAll(docs: Array<{ docId: string; title: string; text: string }>): Chunk[] {
  return docs.flatMap((doc) => chunkDocument(doc.docId, doc.title, doc.text));
}
