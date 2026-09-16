# PhoneHarness iOS runtime — public build.
# Rootful: iOS 13.0+ | Rootless: iOS 15.0+ | Roothide: iOS 15.0+
ARCHS = arm64 arm64e
ifeq ($(THEOS_PACKAGE_SCHEME),rootless)
    TARGET := iphone:clang:latest:15.0
else ifeq ($(THEOS_PACKAGE_SCHEME),roothide)
    TARGET := iphone:clang:latest:15.0
else
    TARGET := iphone:clang:latest:13.0
endif

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = ios-mcp
BUNDLE_NAME = iosmcpprefs

ios-mcp_FILES = Tweak.x MCPServer.m MCPLogger.m HIDManager.m ScreenManager.m ClipboardManager.m \
    AppManager.m AccessibilityManager.m TextInputManager.m FileSystemManager.m LogManager.m \
    OCRManager.m MCPProcessUtil.m MCPAXQueryContext.m MCPAXRemoteContextResolver.m \
    MCPUIElementSerializer.m MCPUIElementsFacade.m MCPAXAttributeBridge.m MCPAXNodeSource.m
ios-mcp_CFLAGS = -fobjc-arc -Wno-unused-function -Wno-deprecated-declarations
ios-mcp_FRAMEWORKS = IOKit UIKit CoreGraphics QuartzCore MobileCoreServices AVFoundation Security Vision ImageIO NaturalLanguage

ifeq ($(THEOS_PACKAGE_SCHEME),roothide)
    ios-mcp_LIBRARIES = roothide
    ios-mcp_CFLAGS += -DMCP_ROOTHIDE=1
    iosmcpprefs_LIBRARIES = roothide
else ifeq ($(THEOS_PACKAGE_SCHEME),rootless)
    ios-mcp_CFLAGS += -DMCP_ROOTLESS=1
endif

iosmcpprefs_FILES = prefs/IOSMCPRootListController.m prefs/IOSMCPQRCodeCell.m MCPLogger.m
iosmcpprefs_CFLAGS = -fobjc-arc
iosmcpprefs_FRAMEWORKS = UIKit CoreGraphics
iosmcpprefs_PRIVATE_FRAMEWORKS = Preferences
iosmcpprefs_LDFLAGS = -F$(THEOS)/sdks/iPhoneOS16.5.sdk/System/Library/PrivateFrameworks
iosmcpprefs_INSTALL_PATH = /Library/PreferenceBundles
iosmcpprefs_RESOURCE_DIRS = prefs/Resources

include $(THEOS_MAKE_PATH)/tweak.mk
include $(THEOS_MAKE_PATH)/bundle.mk

# NOTE: the optional helper tools (mcp-root, mcp-roothelper, mcp-logreader, mcp-ldid)
# are built by their own Makefiles under mcp-*/ and depend on external third-party
# sources that are NOT vendored in this tree. See DEPENDENCIES.md.
after-stage::
	$(ECHO_NOTHING)mkdir -p "$(THEOS_STAGING_DIR)/Library/PreferenceLoader/Preferences"$(ECHO_END)
	$(ECHO_NOTHING)cp prefs/entry/ios-mcp.plist "$(THEOS_STAGING_DIR)/Library/PreferenceLoader/Preferences/ios-mcp.plist"$(ECHO_END)
	$(ECHO_NOTHING)mkdir -p "$(THEOS_STAGING_DIR)/usr/share/doc/ios-mcp"$(ECHO_END)
	$(ECHO_NOTHING)cp NOTICE "$(THEOS_STAGING_DIR)/usr/share/doc/ios-mcp/NOTICE"$(ECHO_END)
	$(ECHO_NOTHING)cp THIRD_PARTY_NOTICES.md "$(THEOS_STAGING_DIR)/usr/share/doc/ios-mcp/THIRD_PARTY_NOTICES.md"$(ECHO_END)
	$(ECHO_NOTHING)python3 scripts/build_identity.py stage --root "$(CURDIR)" --control "$(CURDIR)/control" --output "$(THEOS_STAGING_DIR)/usr/share/doc/ios-mcp/BUILD_IDENTITY.json" --package-scheme "$(THEOS_PACKAGE_SCHEME)" --target "$(TARGET)" --feature-flags "p1-private-journal,p2-visual-session-auth,p3-build-identity"$(ECHO_END)
