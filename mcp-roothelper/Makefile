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

TOOL_NAME = mcp-roothelper

mcp-roothelper_FILES = main.m
mcp-roothelper_CFLAGS += -fobjc-arc -include $(MCP_APPSYNC_DIR)/appinst/zip.h -I$(MCP_APPSYNC_DIR)/appinst -fvisibility=hidden
mcp-roothelper_CCFLAGS += -fobjc-arc -std=c++11 -stdlib=libc++ -include $(MCP_APPSYNC_DIR)/appinst/zip.h -I$(MCP_APPSYNC_DIR)/appinst -fvisibility=hidden
mcp-roothelper_FRAMEWORKS = Foundation
mcp-roothelper_LDFLAGS += $(THEOS)/lib/libzip.a
mcp-roothelper_LIBRARIES = z
mcp-roothelper_USE_MODULES = 0
ifeq ($(THEOS_PACKAGE_SCHEME),roothide)
    mcp-roothelper_CFLAGS += -DMCP_ROOTHIDE=1
    mcp-roothelper_CCFLAGS += -DMCP_ROOTHIDE=1
    mcp-roothelper_LIBRARIES += roothide
    mcp-roothelper_CODESIGN_FLAGS = -Smcp-roothelper_roothide_entitlements.plist
endif
mcp-roothelper_INSTALL_PATH = /usr/bin


# External dependency boundary: mcp-roothelper compiles against the AppSync/appinst
# zip shim, which is NOT vendored in this repository (upstream license:
# GPL-3.0-or-later). Point MCP_APPSYNC_DIR at your own checkout, or skip this tool.
MCP_APPSYNC_DIR ?= ../AppSync

before-all::
	@if [ ! -f "$(MCP_APPSYNC_DIR)/appinst/zip.h" ]; then \
		echo "mcp-roothelper requires the external AppSync/appinst zip shim, which is not vendored."; \
		echo "Provide it (GPL-3.0-or-later) and re-run, e.g.:"; \
		echo "  make MCP_APPSYNC_DIR=/path/to/AppSync package"; \
		echo "See ../DEPENDENCIES.md. This build never downloads or vendors it for you."; \
		exit 1; \
	fi

include $(THEOS_MAKE_PATH)/tool.mk
