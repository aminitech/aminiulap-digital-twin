# Ulap Scope -- reproducible pipeline driver.
# Override interpreters/paths via env (see ulap_scope/config.py):
#   ULAP_PROJECT_ROOT ULAP_BLENDER_BIN ULAP_PREP_PY ULAP_RT_PY
PREP_PY ?= /opt/anaconda3/bin/python
RT_PY   ?= /opt/anaconda3/envs/sionna/bin/python
PY      ?= python3
CLI      = $(PY) -m ulap_scope.cli

.PHONY: help info test test-rt clip preprocess basemap build export coverage \
        analysis mmwave terrain-ground animate all clean

help:
	@echo "targets: info | test | test-rt | all"
	@echo "  stages: clip preprocess basemap build export coverage analysis mmwave terrain-ground animate"
	@echo "  build/export/coverage take MODE=flat|terrain (default flat)"

info:      ; $(CLI) info
MODE ?= flat

clip:            ; $(CLI) clip
preprocess:      ; $(CLI) preprocess
basemap:         ; $(CLI) basemap
build:           ; $(CLI) build --mode $(MODE)
export:          ; $(CLI) export --mode $(MODE)
coverage:        ; $(CLI) coverage --mode $(MODE)
analysis:        ; $(CLI) analysis
mmwave:          ; $(CLI) mmwave-sinr
terrain-ground:  ; $(CLI) terrain-ground
animate:         ; $(CLI) animate
all:             ; $(CLI) all

# ---- tests ----
# fast unit suite (no Blender/Sionna needed; run with the prep python that has numpy+scipy)
test:
	$(PREP_PY) -m pytest

# integration smoke test (needs the Sionna env + an exported scene)
test-rt:
	$(RT_PY) -m pytest -m rt

clean:
	rm -rf .pytest_cache **/__pycache__
