# Barabar. Zero runtime dependencies -- the demo needs Python 3.12 and nothing else.
#
# `make demo` is PRD 14's first acceptance criterion. It runs the whole thing end to end on
# 5,038 payments and prints ingest, the ladder, the close, the buckets, the money findings and
# the written close, then drops into the exception list. `make eval` is the scored version of
# the same run, against the held-out answer key.
#
# Nothing here installs anything. `uv` is used where it is present because it pins the Python
# version; PYTHON= overrides it for a machine that has 3.12 already.

PYTHON ?= $(shell command -v uv >/dev/null 2>&1 && echo "uv run python" || echo python3)
export PYTHONPATH = src

.PHONY: demo run test eval install help

help:
	@echo "./barabar              start here -- what it is, then one prompt"
	@echo "make demo              skip the prompt, run the bundled dataset"
	@echo "make install           put barabar on your PATH"
	@echo "make run DIR=exports/  the close, on your own CSVs"
	@echo "make eval              score against the held-out answer key"
	@echo "make test              the full suite"

# `./barabar` is the first command and opens on the title. `make demo` is the shortcut past
# it, straight onto the bundled held-out set.
demo:
	@$(PYTHON) -m tui demo

run:
	@test -n "$(DIR)" || (echo "usage: make run DIR=path/to/your/csvs"; exit 1)
	@$(PYTHON) -m tui run "$(DIR)"

eval:
	@$(PYTHON) eval/harness.py heldout --r3 gemini

test:
	@$(PYTHON) -m pytest -q

# ~/.local/bin is on the PATH on most systems and needs no sudo. BIN= overrides it.
BIN ?= $(HOME)/.local/bin
install:
	@mkdir -p "$(BIN)"
	@ln -sf "$(CURDIR)/barabar" "$(BIN)/barabar"
	@echo "linked $(BIN)/barabar -> $(CURDIR)/barabar"
	@command -v barabar >/dev/null 2>&1 || echo "note: $(BIN) is not on your PATH yet"
