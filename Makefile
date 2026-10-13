# Everything runs from the source tree; `pip install -e '.[dev]'` first for the tools.
PY ?= python3
RUN := PYTHONPATH=src $(PY) -m slo_proof
EX := examples/sli.csv examples/incidents.csv examples/rules.toml

.PHONY: test lint check examples docs demo clean

test:
	PYTHONPATH=src $(PY) -m pytest -q

lint:
	ruff check .
	ruff format --check .
	mypy

check: lint test

# The committed example month (seed 7) and the README pictures, from the real CLI.
examples:
	$(RUN) synth --seed 7 --days 28 --out examples

docs:
	$(RUN) plot $(EX) -o docs/month.svg --title "Four alert rules replayed against a month with seven incidents"
	$(RUN) plot $(EX) --from 2026-03-18T03:00:00Z --to 2026-03-18T21:00:00Z -o docs/slow-burn.svg \
	  --title "The slow burn: 0.7% errors for 8 hours"

# Re-record docs/demo.gif. Needs Docker; the VHS image has Python 3.11, enough to run slo-proof.
demo: docs
	docker run --rm -u $$(id -u):$$(id -g) -e HOME=/tmp -v $(CURDIR):/vhs ghcr.io/charmbracelet/vhs:v0.10.0 docs/demo.tape

clean:
	rm -rf build dist src/*.egg-info .pytest_cache .mypy_cache .ruff_cache .hypothesis
