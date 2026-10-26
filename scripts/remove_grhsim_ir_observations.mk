# Build observation drivers using copies of the frozen generated Makefiles.
ifeq ($(origin CXX),default)
CXX := clang++
endif
CXXFLAGS ?= -std=c++20 -O3 -fno-strict-aliasing
FIXTURES := dpi_smoke dpi_smoke_tu dpi_bit_abi random_function random_function_tu monitor_free monitor_event monitor_event_tu
OBSERVATION_LIBRARY ?= libgrhsim_phase_*.a

.PHONY: all
all: $(addprefix $(OBSERVATION_DIR)/,$(addsuffix /driver,$(FIXTURES)))

$(OBSERVATION_DIR)/%/driver: $(OBSERVATION_DIR)/%/driver.cpp
	$(MAKE) -C $(@D)/model CXX="$(CXX)" CXXFLAGS="$(CXXFLAGS)"
	$(CXX) $(CXXFLAGS) -I$(@D)/model $< $(@D)/model/$(OBSERVATION_LIBRARY) -o $@
