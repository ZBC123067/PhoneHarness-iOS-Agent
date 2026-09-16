#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>

NS_ASSUME_NONNULL_BEGIN

@interface AccessibilityManager : NSObject

+ (instancetype)sharedInstance;

/// Get frontmost application info resolved from SpringBoard/runtime state.
/// Returns keys like pid, bundleId, name when available.
- (NSDictionary *)frontmostApplicationInfo;

- (void)getCompactUIElementsWithMaxElements:(NSInteger)maxElements
                                visibleOnly:(BOOL)visibleOnly
                              clickableOnly:(BOOL)clickableOnly
                       includeSemanticState:(BOOL)includeSemanticState
                 includeSemanticDiagnostics:(BOOL)includeSemanticDiagnostics
                 expectedValueSHA256:(NSString * _Nullable)expectedValueSHA256
                                 completion:(void (^ _Nullable)(NSDictionary * _Nullable payload, NSString * _Nullable error))completion;

/// TEST-52 opt-in: one primary read; failure never bootstraps or retries.
- (void)getCompactUIElementsWithMaxElements:(NSInteger)maxElements
                                visibleOnly:(BOOL)visibleOnly
                              clickableOnly:(BOOL)clickableOnly
                       includeSemanticState:(BOOL)includeSemanticState
                 includeSemanticDiagnostics:(BOOL)includeSemanticDiagnostics
                        expectedValueSHA256:(NSString * _Nullable)expectedValueSHA256
                        noBootstrapReadOnly:(BOOL)noBootstrapReadOnly
                                 completion:(void (^ _Nullable)(NSDictionary * _Nullable payload, NSString * _Nullable error))completion;

/// Get the accessibility element at a specific screen point
- (void)getElementAtPoint:(CGPoint)point
               completion:(void (^ _Nullable)(NSDictionary * _Nullable element, NSString * _Nullable error))completion;

@end

NS_ASSUME_NONNULL_END
