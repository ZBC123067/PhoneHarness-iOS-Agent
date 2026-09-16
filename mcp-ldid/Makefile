ifeq ($(THEOS_PACKAGE_SCHEME),rootless)
    export TARGET = iphone:clang:latest:15.0
else ifeq ($(THEOS_PACKAGE_SCHEME),roothide)
    export TARGET = iphone:clang:latest:15.0
else
    export TARGET = iphone:clang:latest:13.0
endif
export ARCHS = arm64
export DEBUG = 0

include $(THEOS)/makefiles/common.mk

TOOL_NAME = mcp-ldid

MCP_LDID_SOURCE_DIR ?= $(CURDIR)/../third_party/ldid
MCP_LDID_VENDOR_DIR ?= $(CURDIR)/../third_party/procursus-sdk/iphoneos-arm64
MCP_LDID_VERSION := $(shell cd "$(MCP_LDID_SOURCE_DIR)" && git rev-parse --short HEAD 2>/dev/null || printf 'vendored')

mcp-ldid_FILES = $(MCP_LDID_SOURCE_DIR)/ldid.cpp
mcp-ldid_CFLAGS += -I$(MCP_LDID_SOURCE_DIR) -I$(MCP_LDID_VENDOR_DIR)/usr/include -fvisibility=hidden -Wno-vla-cxx-extension -Wno-unused-but-set-variable -Wno-unused-function
mcp-ldid_CCFLAGS += -std=c++11 -stdlib=libc++ -I$(MCP_LDID_SOURCE_DIR) -I$(MCP_LDID_VENDOR_DIR)/usr/include -fvisibility=hidden -Wno-vla-cxx-extension -Wno-unused-but-set-variable -Wno-unused-function -DLDID_VERSION=\"$(MCP_LDID_VERSION)\"
mcp-ldid_LDFLAGS += $(MCP_LDID_VENDOR_DIR)/usr/lib/libcrypto.a $(MCP_LDID_VENDOR_DIR)/usr/lib/libplist-2.0.a
mcp-ldid_LIBRARIES = xml2 z iconv
mcp-ldid_INSTALL_PATH = /usr/bin
mcp-ldid_USE_MODULES = 0

before-all::
	@if [ ! -f "$(MCP_LDID_SOURCE_DIR)/ldid.cpp" ]; then \
		echo "mcp-ldid requires the external ldid source (AGPL-3.0-only), which is not vendored."; \
		echo "Provide it and re-run, e.g.:  make MCP_LDID_SOURCE_DIR=/path/to/ldid package"; \
		echo "See ../DEPENDENCIES.md. This build never downloads or vendors it for you."; \
		exit 1; \
	fi
	@if [ ! -f "$(MCP_LDID_VENDOR_DIR)/usr/lib/libcrypto.a" ] || [ ! -f "$(MCP_LDID_VENDOR_DIR)/usr/lib/libplist-2.0.a" ]; then \
		echo "mcp-ldid requires the external Procursus SDK static libraries (libcrypto.a / Apache-2.0,"; \
		echo "libplist-2.0.a / LGPL-2.1-or-later), which are not vendored."; \
		echo "Provide them and re-run, e.g.:  make MCP_LDID_VENDOR_DIR=/path/to/procursus-sdk/iphoneos-arm64 package"; \
		echo "See ../DEPENDENCIES.md."; \
		exit 1; \
	fi

include $(THEOS_MAKE_PATH)/tool.mk
