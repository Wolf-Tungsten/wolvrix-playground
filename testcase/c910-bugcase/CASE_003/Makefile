ROOT := $(abspath ../../..)

CASE_ID := 003
CASE_TAG := CASE_$(CASE_ID)
CASE_DIR := $(CURDIR)

FILELIST := $(CASE_DIR)/filelist.f
SCRIPT := $(CASE_DIR)/run_wolvrix.py

OUT_DIR := $(ROOT)/build/c910_bugcase/$(CASE_TAG)

PYTHON ?= python3
WOLVRIX_PY ?= $(PYTHON)
PIP ?= $(PYTHON) -m pip

.PHONY: run clean install_wolvrix

run: $(FILELIST)
	@mkdir -p $(OUT_DIR)
	@OUT_DIR=$(OUT_DIR) $(WOLVRIX_PY) $(SCRIPT)

install_wolvrix:
	@PIP_DISABLE_PIP_VERSION_CHECK=1 $(PIP) install --no-build-isolation $(PIP_CONFIG_SETTINGS) -e $(ROOT)/wolvrix

clean:
	@rm -rf $(OUT_DIR)
