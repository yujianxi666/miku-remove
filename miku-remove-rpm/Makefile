# miku-voicebank (Fedora / RHEL) - build the 51 package rpm chain.
#
#   make rpms      -> dist/*.rpm
#   make check     -> parse the built packages back independently
#   make test      -> run miku-show's self tests
#   make all       -> test + rpms + check
#   make clean

COUNT     ?= 51
AUDIO_URL ?= https://fms.uiero.com/downloads/mkrm.mp3
OFFSET    ?= 25.6

PYTHON ?= python3

.PHONY: all rpms check test clean

all: test rpms check

rpms:
	$(PYTHON) tools/build_rpm.py --count $(COUNT) --offset $(OFFSET) --audio-url "$(AUDIO_URL)"

check:
	$(PYTHON) tools/_check_rpm.py dist/*.rpm

test:
	$(PYTHON) tests/test_show.py
	$(PYTHON) tests/test_tick.py

clean:
	rm -rf dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
