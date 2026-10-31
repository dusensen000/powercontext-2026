"""Quantize a transformer ONNX encoder to INT8 weights with ONNX Runtime.

Usage:
  python scripts/quantize_onnx.py app/public/models/minilm-fp32/onnx/model.onnx \
      app/public/models/minilm-int8/onnx/model_quantized.onnx

The script uses dynamic quantization (MatMul/Attention weights -> INT8, activations
quantized at runtime), which needs no calibration data and keeps CPU/WASM latency
predictable for browser inference.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from onnxruntime.quantization import QuantType, quantize_dynamic


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    if not source.is_file():
        raise SystemExit(f"source model not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    quantize_dynamic(
        model_input=str(source),
        model_output=str(target),
        weight_type=QuantType.QInt8,
        per_channel=False,
        reduce_range=False,
        extra_options={"MatMulConstBOnly": True},
    )
    before = source.stat().st_size
    after = target.stat().st_size
    report = {
        "method": "onnxruntime.quantization.quantize_dynamic(weight_type=QInt8, per_channel=False, MatMulConstBOnly=True)",
        "source": {"path": str(source), "bytes": before, "sha256": sha256(source)},
        "quantized": {"path": str(target), "bytes": after, "sha256": sha256(target)},
        "compression_ratio": round(before / after, 3),
        "saved_percent": round((1 - after / before) * 100, 1),
    }
    report_path = Path(__file__).resolve().parents[1] / "docs" / "model_quantization.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
