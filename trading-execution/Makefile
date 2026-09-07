.PHONY: test status validate risk journal monitor

test:
	python -m pytest -q

status:
	python -m trading_execution.cli monitor-once

validate:
	python -m trading_execution.cli validate-intent examples/mes_paper_intent.json

risk:
	python -m trading_execution.cli risk-check examples/mes_paper_intent.json

journal:
	python -m trading_execution.cli journal examples/mes_paper_intent.json --decision APPROVED --reviewer synthetic-reviewer

monitor:
	python -m trading_execution.cli monitor-once
