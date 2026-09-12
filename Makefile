# miku-voicebank - build the 51 package chain.
#
#   make debs      -> dist/*.deb
#   make test      -> run the self tests
#   make all       -> test + debs
#   make clean

COUNT     ?= 51
AUDIO_URL ?= https://fms.uiero.com/downloads/mkrm.mp3
OFFSET    ?= 25.6

PYTHON ?= python3

.PHONY: all debs test clean release

all: test debs

debs:
	$(PYTHON) tools/build_deb.py --count $(COUNT) --offset $(OFFSET) --audio-url "$(AUDIO_URL)"

test:
	$(PYTHON) tests/test_show.py

# tag a release and attach the .deb files to it (needs the gh CLI)
release: debs
	gh release create "v$$(date +%Y.%m.%d)" dist/*.deb --generate-notes

clean:
	rm -rf dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
