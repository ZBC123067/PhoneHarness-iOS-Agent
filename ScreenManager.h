#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>

@interface ScreenManager : NSObject

+ (instancetype)sharedInstance;

/// Get screen info: width, height, scale, orientation
- (NSDictionary *)screenInfo;

/// Best-effort device interaction state from SpringBoard private APIs.
- (NSDictionary *)deviceInteractionState;

/// Take screenshot and return encoded image payload with data/mimeType.
- (NSDictionary *)takeScreenshotPayload;

/// Capture the current screen as a UIImage (for in-process OCR). Runs capture on the
/// main thread. Returns nil if all private capture paths fail.
- (UIImage *)captureScreenImage;

@end
