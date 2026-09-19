# miku-voicebank (Fedora / RHEL) - build the 51 package rpm chain.
#
#   make rpms      -> dist/*.rpm          (needs rpmbuild: dnf install rpm-build)
#   make check     -> verify the built packages with rpm
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
	@command -v rpmbuild >/dev/null 2>&1 || { \
	  echo "rpmbuild not found: sudo dnf install rpm-build"; exit 1; }
	$(PYTHON) tools/build_rpm.py --count $(COUNT) --offset $(OFFSET) --audio-url "$(AUDIO_URL)"

check:
	$(PYTHON) tools/_check_rpm.py dist/*.rpm

test:
	$(PYTHON) tests/test_show.py
	$(PYTHON) tests/test_tick.py

clean:
	rm -rf dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
