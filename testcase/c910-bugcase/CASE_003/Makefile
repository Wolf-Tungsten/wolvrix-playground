ROOT := $(abspath ../../..)

CASE_ID := 003
CASE_TAG := CASE_$(CASE_ID)
CASE_DIR := $(CURDIR)

FILELIST := $(CASE_DIR)/filelist.f
SCRIPT := $(CASE_DIR)/run_wolvrix.py

OUT_DIR := $(ROOT)/build/c910_bugcase/$(CASE_TAG)

PYTHON ?= python3
PYTHON_FLAGS ?= -S
PYTHONPATH := $(ROOT)/wolvrix/build/python$(if $(PYTHONPATH),:$(PYTHONPATH),)
WOLVRIX_PY := PYTHONPATH=$(PYTHONPATH) $(PYTHON) $(PYTHON_FLAGS)
PIP ?= $(WOLVRIX_PY) -m pip

.PHONY: run clean install_wolvrix

run: $(FILELIST)
	@mkdir -p $(OUT_DIR)
	@OUT_DIR=$(OUT_DIR) $(WOLVRIX_PY) $(SCRIPT)

install_wolvrix:
	@PIP_DISABLE_PIP_VERSION_CHECK=1 $(PIP) install -e $(ROOT)/wolvrix --no-build-isolation $(PIP_CONFIG_SETTINGS)

clean:
	@rm -rf $(OUT_DIR)
