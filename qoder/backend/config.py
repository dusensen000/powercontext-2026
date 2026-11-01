from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

STEP_API_KEY = os.environ["STEP_API_KEY"]
STEP_BASE_URL = os.getenv("STEP_BASE_URL", "https://api.stepfun.com/v1")
STEP_MODEL = os.getenv("STEP_MODEL", "step-3.5-flash")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
# WSL 内访问不到 huggingface.co，模型下载走镜像；必须在导入 sentence_transformers 之前设置
_hf_endpoint = os.getenv("HF_ENDPOINT", "")
if _hf_endpoint:
    os.environ["HF_ENDPOINT"] = _hf_endpoint

SEEKDB_PATH = Path(os.getenv("SEEKDB_PATH", "~/relay-data/seekdb.db")).expanduser()
SEEKDB_DATABASE = os.getenv("SEEKDB_DATABASE", "relay")
SEEKDB_COLLECTION = os.getenv("SEEKDB_COLLECTION", "work_items")

# 设了 SEEKDB_HOST 就走 server 模式（python-client-db），否则用嵌入式库文件
SEEKDB_HOST = os.getenv("SEEKDB_HOST", "")
SEEKDB_PORT = int(os.getenv("SEEKDB_PORT", "2882"))
SEEKDB_USER = os.getenv("SEEKDB_USER", "root")
SEEKDB_PASSWORD = os.getenv("SEEKDB_PASSWORD", "")
SEEKDB_USE_SERVER = bool(SEEKDB_HOST)

DEDUPE_THRESHOLD = float(os.getenv("DEDUPE_THRESHOLD", "0.62"))

POWERCONTEXT_BASE_URL = os.getenv("POWERCONTEXT_BASE_URL", "http://127.0.0.1:8000")
POWERCONTEXT_SCOPE_ID = os.getenv("POWERCONTEXT_SCOPE_ID", "")
POWERCONTEXT_TOKEN = os.getenv("POWERCONTEXT_TOKEN", "")
# setup_powercontext.py 建好 Scope 后写在这里，省得每次手改 .env
SCOPE_FILE = PROJECT_ROOT / "data" / "out" / "powercontext-scope.json"

SAMPLES_DIR = PROJECT_ROOT / "data" / "samples"


def ensure_seekdb_dir() -> None:
    if not SEEKDB_USE_SERVER:
        SEEKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
