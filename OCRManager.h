#import <Foundation/Foundation.h>

/// On-device OCR via the Vision framework. Captures the current screen, recognizes text,
/// and returns each text block with screen-point coordinates (ready for tap_screen).
@interface OCRManager : NSObject

+ (instancetype)sharedInstance;

/// Recognize text on the current screen.
///   languages:     recognition languages (e.g. @[@"zh-Hans", @"en"]); nil = default.
///   minConfidence: drop results below this confidence (0..1).
///   region:        optional screen-point rect {x,y,width,height} to limit OCR; nil = full screen.
///   fast:          YES uses Vision's fast recognition (~10x faster, fewer/less-accurate
///                  results, weaker on small/CJK text); NO uses accurate (default).
/// Returns a dict with "texts" (text/confidence/rect/tap), "count", "screen", or nil with *error.
- (NSDictionary *)recognizeTextWithLanguages:(NSArray<NSString *> *)languages
                               minConfidence:(double)minConfidence
                                      region:(NSDictionary *)region
                                        fast:(BOOL)fast
                                       error:(NSString **)error;

/// Recognize the current screen for one authorized, temporary TEST-44.3
/// visual session. This deliberately returns Vision-normalized boxes and
/// transient OCR text only; it does not expose tap points, screenshots, or a
/// device-specific geometry assumption. The caller owns immediate disposal.
- (NSDictionary *)recognizeTemporaryVisualSessionWithRecognitionMode:(NSString *)recognitionMode
                                                                 error:(NSString **)error;

@end
