# miku-voicebank (Arch Linux) - build the 51 package pacman chain.
#
#   make pkgs      -> dist/*.pkg.tar.zst
#   make check     -> unpack the built packages back independently
#   make test      -> run miku-show's self tests
#   make all       -> test + pkgs + check
#   make clean

COUNT     ?= 51
AUDIO_URL ?= https://fms.uiero.com/downloads/mkrm.mp3
OFFSET    ?= 25.6

PYTHON ?= python3

.PHONY: all pkgs check test clean

all: test pkgs check

pkgs:
	$(PYTHON) tools/build_pkg.py --count $(COUNT) --offset $(OFFSET) --audio-url "$(AUDIO_URL)"

check:
	$(PYTHON) tools/_check_pkg.py dist/*.pkg.tar.zst

test:
	$(PYTHON) tests/test_show.py
	$(PYTHON) tests/test_tick.py

clean:
	rm -rf dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
