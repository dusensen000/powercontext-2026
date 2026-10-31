.PHONY: install ingest context agent test demo state clean

PY ?= python3
export SDDCTX_DB_BACKEND ?= seekdb
export POWERCONTEXT_STATE_BACKEND ?= powercontext

install:
	$(PY) -m pip install -r requirements.txt

ingest:
	$(PY) -m sddctx ingest

context:
	$(PY) -m sddctx context --write

agent:
	$(PY) -m sddctx run-agent

test:
	$(PY) -m sddctx test all

state:
	$(PY) -m sddctx state-load

demo:
	$(PY) -m sddctx demo

clean:
	rm -rf .work .data
	rm -f artifacts/report.json artifacts/context*.json artifacts/context*.md \
	      artifacts/diff.patch artifacts/dev_record.json artifacts/db_queries.log \
	      artifacts/state_ops.log
	rm -rf artifacts/prompts artifacts/test_logs
