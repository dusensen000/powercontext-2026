#!/usr/bin/env bash
# Download the FP32 ONNX encoder and build the INT8 model used by the browser app.
#
#   bash scripts/fetch-models.sh
#
# Environment:
#   HF_BASE   mirror base URL (default https://hf-mirror.com)
#   PYTHON    python interpreter with onnxruntime (default python3)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/app/public/models"
HF_BASE="${HF_BASE:-https://hf-mirror.com}"
# Xenova/all-MiniLM-L6-v2 @ 751bff37182d3f1213fa05d7196b954e230abad9
MODEL_REV="751bff37182d3f1213fa05d7196b954e230abad9"
BASE="$HF_BASE/Xenova/all-MiniLM-L6-v2/resolve/$MODEL_REV"
PYTHON="${PYTHON:-python3}"

mkdir -p "$DEST/minilm-fp32/onnx" "$DEST/minilm-int8/onnx"

for file in config.json tokenizer.json tokenizer_config.json special_tokens_map.json; do
  echo "download $file"
  curl -fL --retry 3 "$BASE/$file" -o "$DEST/minilm-fp32/$file"
done

echo "download onnx/model.onnx"
curl -fL --retry 3 "$BASE/onnx/model.onnx" -o "$DEST/minilm-fp32/onnx/model.onnx"

cp "$DEST/minilm-fp32/"*.json "$DEST/minilm-int8/"

echo "quantize -> onnx/model_quantized.onnx"
"$PYTHON" "$ROOT/scripts/quantize_onnx.py" \
  "$DEST/minilm-fp32/onnx/model.onnx" \
  "$DEST/minilm-int8/onnx/model_quantized.onnx"

ls -l "$DEST/minilm-fp32/onnx" "$DEST/minilm-int8/onnx"
