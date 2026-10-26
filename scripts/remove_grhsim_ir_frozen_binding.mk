# Isolated R0 binding; all GRH/GrhSIM inline definitions come from R0 headers.
CXX := clang++
BINDING_SOURCE := $(BINDING_DIR)/source/wolvrix
BINDING_PACKAGE := $(BINDING_DIR)/python/wolvrix
BINDING_SOURCES := $(shell find $(BINDING_SOURCE)/app/pybind -name '*.cpp' -type f | sort)
BINDING_OBJECTS := $(patsubst $(BINDING_SOURCE)/app/pybind/%.cpp,$(BINDING_DIR)/objects/%.o,$(BINDING_SOURCES))
CPPFLAGS := -I$(BINDING_SOURCE)/app/pybind -I$(BINDING_SOURCE)/include \
    -I$(REPO_ROOT)/wolvrix/external/slang/include -I$(REPO_ROOT)/wolvrix/build/external/slang/source \
    -I$(REPO_ROOT)/wolvrix/external/slang/external -I$(REPO_ROOT)/wolvrix/build/_deps/fmt-src/include \
    -I$(REPO_ROOT)/wolvrix/build/_deps/mimalloc-src/include -I/usr/include/python3.12 \
    -DSLANG_BOOST_SINGLE_HEADER -DSLANG_STATIC_DEFINE -DSLANG_USE_MIMALLOC -DSLANG_USE_THREADS \
    -DWOLVRIX_HAVE_LIBFST=1 -DWOLVRIX_HAVE_MT_KAHYPAR=1
CXXFLAGS := -std=c++20 -O3 -DNDEBUG -fPIC
CPPFLAGS += -I$(REPO_ROOT)/wolvrix/external/mt-kahypar/include -I$(REPO_ROOT)/wolvrix/external/libfst/src

ifeq ($(REBUILD_FROZEN_COMPILER),1)
include $(BINDING_DIR)/compiler-sources.mk
FROZEN_COMPILER_OBJECTS := $(patsubst %.cpp,$(BINDING_DIR)/compiler-objects/%.o,$(FROZEN_COMPILER_SOURCES))
CPPFLAGS += -DWOLVRIX_SOURCE_DIR=\"$(REPO_ROOT)/wolvrix\"
$(BINDING_DIR)/compiler-objects/%.o: $(BINDING_SOURCE)/%.cpp
	mkdir -p $(dir $@)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@
$(BINDING_PACKAGE)/libwolvrix-lib.so: $(FROZEN_COMPILER_OBJECTS)
	$(CXX) -shared -fuse-ld=lld -Wl,-soname,libwolvrix-lib.so -o $@ $(FROZEN_COMPILER_OBJECTS) \
	    -Wl,-rpath,$(REPO_ROOT)/wolvrix/build/clang_22.1_cxx20_64_release \
	    $(REPO_ROOT)/wolvrix/build/external/slang/lib/libsvlang.a \
	    $(REPO_ROOT)/wolvrix/build/external/mt-kahypar/lib/libmtkahypar.a \
	    $(REPO_ROOT)/wolvrix/build/libwolvrix-libfst.a \
	    $(REPO_ROOT)/wolvrix/build/external/slang/lib/libfmt.a \
	    $(REPO_ROOT)/wolvrix/build/external/slang/lib/libmimalloc.a -lpthread -lrt -latomic \
	    $(REPO_ROOT)/wolvrix/build/clang_22.1_cxx20_64_release/libtbb.so.12.14 \
	    $(REPO_ROOT)/wolvrix/build/clang_22.1_cxx20_64_release/libtbbmalloc.so.2.14 -lhwloc -lz
-include $(FROZEN_COMPILER_OBJECTS:.o=.d)
endif

.DEFAULT_GOAL := all
.PHONY: all
all: $(BINDING_PACKAGE)/_wolvrix.so
$(BINDING_DIR)/objects/%.o: $(BINDING_SOURCE)/app/pybind/%.cpp
	mkdir -p $(dir $@)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@
$(BINDING_PACKAGE)/_wolvrix.so: $(BINDING_OBJECTS) $(BINDING_PACKAGE)/libwolvrix-lib.so
	$(CXX) -shared -o $@ $(BINDING_OBJECTS) -L$(BINDING_PACKAGE) -Wl,-rpath,'$$ORIGIN' -lwolvrix-lib \
	    $(REPO_ROOT)/wolvrix/build/external/slang/lib/libsvlang.a \
	    $(REPO_ROOT)/wolvrix/build/external/slang/lib/libfmt.a \
	    $(REPO_ROOT)/wolvrix/build/external/slang/lib/libmimalloc.a -lpthread -lrt -latomic
-include $(BINDING_OBJECTS:.o=.d)
