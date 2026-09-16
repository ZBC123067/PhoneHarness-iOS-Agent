ifeq ($(THEOS_PACKAGE_SCHEME),rootless)
    export TARGET = iphone:clang:latest:15.0
else ifeq ($(THEOS_PACKAGE_SCHEME),roothide)
    export TARGET = iphone:clang:latest:15.0
else
    export TARGET = iphone:clang:latest:13.0
endif
export ARCHS = arm64 arm64e
export DEBUG = 0

include $(THEOS)/makefiles/common.mk

TOOL_NAME = mcp-logreader
mcp-logreader_FILES = main.m
mcp-logreader_CFLAGS = -fobjc-arc -fvisibility=hidden
mcp-logreader_FRAMEWORKS = Foundation
# OSLogEventLiveStream lives in the private LoggingSupport framework; link weakly and
# dlopen at runtime so the binary loads even where the framework path differs.
mcp-logreader_LDFLAGS = -Wl,-U,_OBJC_CLASS_$$_OSLogEventLiveStream
# Fake-sign with com.apple.private.logging.stream so we can connect to diagnosticd.
mcp-logreader_CODESIGN_FLAGS = -Smcp-logreader_entitlements.plist
ifeq ($(THEOS_PACKAGE_SCHEME),roothide)
    mcp-logreader_CFLAGS += -DMCP_ROOTHIDE=1
    mcp-logreader_LIBRARIES = roothide
endif
mcp-logreader_INSTALL_PATH = /usr/bin

include $(THEOS_MAKE_PATH)/tool.mk
