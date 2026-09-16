#import "OCRManager.h"
#import "ScreenManager.h"
#import "MCPLogger.h"
#import <UIKit/UIKit.h>
#import <Vision/Vision.h>
#import <ImageIO/ImageIO.h>
#import <NaturalLanguage/NaturalLanguage.h>
#import <mach/mach.h>
#import <math.h>

#define OCR_LOG(fmt, ...) [MCPLogger log:@"[OCR] " fmt, ##__VA_ARGS__]

@implementation OCRManager

+ (instancetype)sharedInstance {
    static OCRManager *instance = nil;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        instance = [[OCRManager alloc] init];
    });
    return instance;
}

static double OCRNum(NSDictionary *d, NSString *k) {
    id v = d[k];
    return [v respondsToSelector:@selector(doubleValue)] ? [v doubleValue] : 0.0;
}

static uint64_t OCRResidentBytes(void) {
    mach_task_basic_info_data_t info;
    mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
    kern_return_t result = task_info(mach_task_self(), MACH_TASK_BASIC_INFO, (task_info_t)&info, &count);
    return result == KERN_SUCCESS ? (uint64_t)info.resident_size : 0;
}

static UIImage *OCRNormalizeOrientation(UIImage *image) {
    if (!image || image.imageOrientation == UIImageOrientationUp) return image;
    UIGraphicsBeginImageContextWithOptions(image.size, NO, image.scale);
    [image drawInRect:(CGRect){CGPointZero, image.size}];
    UIImage *normalized = UIGraphicsGetImageFromCurrentImageContext();
    UIGraphicsEndImageContext();
    return normalized ?: image;
}

static NSArray<NSDictionary *> *OCRLanguageHypotheses(NSString *text) {
    if (text.length == 0) return @[];
    // The recognizer is deliberately allocated per OCR region. NaturalLanguage
    // objects hold state while processing text and are not shared across
    // concurrent visual sessions.
    NSDictionary<NLLanguage, NSNumber *> *hypotheses = nil;
    @try {
        NLLanguageRecognizer *recognizer = [[NLLanguageRecognizer alloc] init];
        [recognizer processString:text];
        hypotheses = [recognizer languageHypothesesWithMaximum:3];
    } @catch (NSException *exception) {
        // Language hints are advisory metadata. A framework failure must not
        // abort OCR or expose the transient recognized text in an error path.
        OCR_LOG(@"language hypothesis unavailable exception class=%@", exception.name ?: @"unknown");
        return @[];
    }
    hypotheses = hypotheses ?: @{};
    NSArray<NLLanguage> *languages = [hypotheses.allKeys sortedArrayUsingComparator:^NSComparisonResult(NLLanguage a, NLLanguage b) {
        double aConfidence = [hypotheses[a] doubleValue];
        double bConfidence = [hypotheses[b] doubleValue];
        if (aConfidence > bConfidence) return NSOrderedAscending;
        if (aConfidence < bConfidence) return NSOrderedDescending;
        return [a compare:b];
    }];
    NSMutableArray<NSDictionary *> *result = [NSMutableArray arrayWithCapacity:languages.count];
    for (NLLanguage language in languages) {
        if (result.count >= 3 || language.length == 0) continue;
        [result addObject:@{
            @"language": language,
            @"confidence": @([hypotheses[language] doubleValue])
        }];
    }
    return result;
}

// Downsample a CGImage so its longest edge is at most maxEdge pixels, via CoreGraphics.
// Vision text recognition does not need full-resolution input; shrinking a large iPad
// capture (e.g. 1620x2160) cuts recognition time several fold. Returns NULL if no
// downsample is needed or on failure (caller then keeps the original). Coordinate mapping
// is unaffected: results are mapped back using the logical UIImage.size, not pixel size.
static CGImageRef OCRCreateDownsampled(CGImageRef src, CGFloat maxEdge) CF_RETURNS_RETAINED {
    if (!src) return NULL;
    size_t w = CGImageGetWidth(src);
    size_t h = CGImageGetHeight(src);
    size_t longEdge = MAX(w, h);
    if (longEdge == 0 || longEdge <= (size_t)maxEdge) return NULL;

    double scale = maxEdge / (double)longEdge;
    size_t nw = (size_t)(w * scale);
    size_t nh = (size_t)(h * scale);
    if (nw == 0 || nh == 0) return NULL;

    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = CGBitmapContextCreate(NULL, nw, nh, 8, 0, cs,
                                             kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);
    CGColorSpaceRelease(cs);
    if (!ctx) return NULL;
    CGContextSetInterpolationQuality(ctx, kCGInterpolationMedium);
    CGContextDrawImage(ctx, CGRectMake(0, 0, nw, nh), src);
    CGImageRef out = CGBitmapContextCreateImage(ctx);
    CGContextRelease(ctx);
    return out;
}

- (NSDictionary *)recognizeTextWithLanguages:(NSArray<NSString *> *)languages
                               minConfidence:(double)minConfidence
                                      region:(NSDictionary *)region
                                        fast:(BOOL)fast
                                       error:(NSString **)error {
    if (error) *error = nil;

    if (@available(iOS 13.0, *)) {
        UIImage *image = [[ScreenManager sharedInstance] captureScreenImage];
        if (!image || !image.CGImage) {
            if (error) *error = @"Failed to capture screen for OCR";
            return nil;
        }

        // UIImage.size is in points and matches the screen's logical size; OCR results are
        // mapped back to these points so the returned rect/tap are tap_screen-ready.
        CGFloat W = image.size.width;
        CGFloat H = image.size.height;

        __block NSArray<VNRecognizedTextObservation *> *observations = nil;
        __block NSError *visionError = nil;

        VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] initWithCompletionHandler:^(VNRequest *req, NSError *err) {
            visionError = err;
            observations = (NSArray<VNRecognizedTextObservation *> *)req.results;
        }];
        request.recognitionLevel = fast ? VNRequestTextRecognitionLevelFast : VNRequestTextRecognitionLevelAccurate;
        request.usesLanguageCorrection = !fast; // fast 模式跳过语言矫正以最大化速度
        if (languages.count > 0) {
            request.recognitionLanguages = languages;
        } else {
            request.recognitionLanguages = @[@"zh-Hans", @"en-US"];
        }

        // Limit OCR to a region of interest if provided (Vision uses normalized, origin bottom-left).
        if ([region isKindOfClass:[NSDictionary class]] && region.count > 0 && W > 0 && H > 0) {
            double rx = OCRNum(region, @"x"), ry = OCRNum(region, @"y");
            double rw = OCRNum(region, @"width"), rh = OCRNum(region, @"height");
            if (rw > 0 && rh > 0) {
                double nx = rx / W;
                double nw = rw / W;
                double nh = rh / H;
                double ny = 1.0 - (ry + rh) / H; // flip Y
                request.regionOfInterest = CGRectMake(MAX(0, nx), MAX(0, ny), MIN(1, nw), MIN(1, nh));
            }
        }

        // Downsample large captures before OCR (longest edge cap). Speeds up Vision on
        // high-res iPad screens; coordinates still map back via the logical image.size.
        CGImageRef ocrImage = image.CGImage;
        CGImageRef downsampled = OCRCreateDownsampled(image.CGImage, 1600.0);
        if (downsampled) ocrImage = downsampled;

        VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:ocrImage options:@{}];
        NSError *performError = nil;
        BOOL ok = [handler performRequests:@[request] error:&performError];

        // iOS 14's Vision can fail the accurate recognition level with an internal error
        // ("VNRecognizeTextRequest produced an internal error"). Fall back to the fast level
        // once so OCR still returns results instead of failing outright.
        if ((!ok || visionError) && !fast) {
            OCR_LOG(@"accurate failed (%@), retrying with fast level",
                    (performError ?: visionError).localizedDescription ?: @"?");
            observations = nil; visionError = nil;
            VNRecognizeTextRequest *fastReq = [[VNRecognizeTextRequest alloc] initWithCompletionHandler:^(VNRequest *req, NSError *err) {
                visionError = err;
                observations = (NSArray<VNRecognizedTextObservation *> *)req.results;
            }];
            fastReq.recognitionLevel = VNRequestTextRecognitionLevelFast;
            fastReq.usesLanguageCorrection = NO;
            fastReq.recognitionLanguages = request.recognitionLanguages;
            fastReq.regionOfInterest = request.regionOfInterest;
            VNImageRequestHandler *h2 = [[VNImageRequestHandler alloc] initWithCGImage:ocrImage options:@{}];
            performError = nil;
            ok = [h2 performRequests:@[fastReq] error:&performError];
        }

        if (downsampled) CGImageRelease(downsampled);
        if (!ok || visionError) {
            NSString *msg = (performError ?: visionError).localizedDescription ?: @"Vision OCR failed";
            if (error) *error = msg;
            OCR_LOG(@"failed: %@", msg);
            return nil;
        }

        NSMutableArray<NSDictionary *> *texts = [NSMutableArray array];
        for (VNRecognizedTextObservation *obs in observations) {
            VNRecognizedText *top = [[obs topCandidates:1] firstObject];
            if (!top) continue;
            double conf = top.confidence;
            if (conf < minConfidence) continue;

            NSString *str = top.string ?: @"";
            if (str.length == 0) continue;

            // boundingBox is normalized (0..1), origin bottom-left. Map to screen points.
            CGRect bb = obs.boundingBox;
            double x = bb.origin.x * W;
            double w = bb.size.width * W;
            double h = bb.size.height * H;
            double y = (1.0 - bb.origin.y - bb.size.height) * H; // flip Y to top-left origin

            int ix = (int)round(x), iy = (int)round(y);
            int iw = (int)round(w), ih = (int)round(h);

            [texts addObject:@{
                @"text": str,
                @"confidence": @(round(conf * 100) / 100.0),
                @"rect": @{@"x": @(ix), @"y": @(iy), @"width": @(iw), @"height": @(ih)},
                @"tap": @{@"x": @(ix + iw / 2), @"y": @(iy + ih / 2)}
            }];
        }

        OCR_LOG(@"ok count=%lu langs=%@", (unsigned long)texts.count, request.recognitionLanguages);
        return @{
            @"texts": texts,
            @"count": @(texts.count),
            @"screen": @{@"width": @((int)round(W)), @"height": @((int)round(H))}
        };
    }

    if (error) *error = @"OCR requires iOS 13 or later";
    return nil;
}

- (NSDictionary *)recognizeTemporaryVisualSessionWithRecognitionMode:(NSString *)recognitionMode
                                                                 error:(NSString **)error {
    if (error) *error = nil;
    if (@available(iOS 13.0, *)) {
        // Vision is available below; the branch makes the deployment boundary
        // explicit without relying on a device-model assumption.
    } else {
        if (error) *error = @"Local visual recognition is unavailable";
        return nil;
    }

    BOOL fast = [recognitionMode isEqualToString:@"fast"];
    if (!fast && ![recognitionMode isEqualToString:@"accurate"]) {
        if (error) *error = @"Invalid local visual recognition mode";
        return nil;
    }

    uint64_t residentBefore = OCRResidentBytes();
    CFAbsoluteTime startedAt = CFAbsoluteTimeGetCurrent();
    UIImage *captured = [[ScreenManager sharedInstance] captureScreenImage];
    UIImage *image = OCRNormalizeOrientation(captured);
    if (!image || !image.CGImage || image.size.width <= 0.0 || image.size.height <= 0.0 || image.scale <= 0.0) {
        if (error) *error = @"Failed to capture screen for local visual recognition";
        return nil;
    }

    size_t sourceWidth = CGImageGetWidth(image.CGImage);
    size_t sourceHeight = CGImageGetHeight(image.CGImage);
    if (sourceWidth == 0 || sourceHeight == 0) {
        if (error) *error = @"Invalid local visual frame";
        return nil;
    }

    CGImageRef analyzedImage = image.CGImage;
    CGImageRef downsampled = OCRCreateDownsampled(image.CGImage, 1600.0);
    if (downsampled) analyzedImage = downsampled;
    size_t analyzedWidth = CGImageGetWidth(analyzedImage);
    size_t analyzedHeight = CGImageGetHeight(analyzedImage);

    __block NSArray<VNRecognizedTextObservation *> *observations = nil;
    __block NSError *visionError = nil;
    BOOL (^performRecognition)(BOOL) = ^BOOL(BOOL useFast) {
        observations = nil;
        visionError = nil;
        @try {
            VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] initWithCompletionHandler:^(VNRequest *req, NSError *requestError) {
                visionError = requestError;
                observations = (NSArray<VNRecognizedTextObservation *> *)req.results;
            }];
            request.recognitionLevel = useFast ? VNRequestTextRecognitionLevelFast : VNRequestTextRecognitionLevelAccurate;
            request.usesLanguageCorrection = !useFast;
            request.recognitionLanguages = @[@"zh-Hans", @"en-US"];

            // OCRNormalizeOrientation has rendered the captured UIKit image upright.
            // Vision boxes therefore use the documented normalized lower-left frame.
            VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:analyzedImage
                                                                                  orientation:kCGImagePropertyOrientationUp
                                                                                     options:@{}];
            NSError *performError = nil;
            BOOL completed = [handler performRequests:@[request] error:&performError];
            return completed && visionError == nil;
        } @catch (NSException *exception) {
            // Never let a Vision implementation exception cross the private MCP
            // boundary. The caller receives only a controlled result.
            OCR_LOG(@"local visual recognition exception class=%@", exception.name ?: @"unknown");
            observations = nil;
            visionError = [NSError errorWithDomain:@"PhoneHarness.LocalVision"
                                                code:1
                                            userInfo:nil];
            return NO;
        }
    };

    BOOL effectiveFast = fast;
    BOOL completed = performRecognition(effectiveFast);
    // The established OCR path uses an accurate-to-fast retry for iOS Vision
    // failures. Preserve the same resilience here without exposing underlying
    // framework errors or screen content outside this temporary method.
    if (!completed && !fast) {
        OCR_LOG(@"local visual recognition accurate mode failed; retrying fast mode");
        effectiveFast = YES;
        completed = performRecognition(YES);
    }
    if (downsampled) CGImageRelease(downsampled);
    if (!completed || visionError) {
        if (error) *error = @"Local visual recognition failed";
        OCR_LOG(@"local visual recognition failed mode=%@", recognitionMode);
        return nil;
    }

    NSMutableArray<NSDictionary *> *temporaryObservations = [NSMutableArray array];
    for (VNRecognizedTextObservation *observation in observations ?: @[]) {
        // Bound transient transport as well as the Mac-side session store. A
        // densely populated screen must not turn one read-only request into an
        // unbounded private payload.
        if (temporaryObservations.count >= 128) break;
        VNRecognizedText *top = [[observation topCandidates:1] firstObject];
        NSString *text = top.string ?: @"";
        if (text.length == 0) continue;
        CGRect box = observation.boundingBox;
        if (box.origin.x < 0.0 || box.origin.y < 0.0 || box.size.width <= 0.0 || box.size.height <= 0.0 ||
            CGRectGetMaxX(box) > 1.000001 || CGRectGetMaxY(box) > 1.000001) {
            continue;
        }
        [temporaryObservations addObject:@{
            @"recognized_text": text,
            @"confidence": @(top.confidence),
            @"language_hypotheses": OCRLanguageHypotheses(text),
            @"vision_box": @{
                @"x": @(box.origin.x),
                @"y": @(box.origin.y),
                @"width": @(box.size.width),
                @"height": @(box.size.height)
            }
        }];
    }

    uint64_t residentAfter = OCRResidentBytes();
    uint64_t residentDelta = residentAfter > residentBefore ? residentAfter - residentBefore : 0;
    NSInteger latencyMs = (NSInteger)llround((CFAbsoluteTimeGetCurrent() - startedAt) * 1000.0);
    uint64_t inputPixels = (uint64_t)sourceWidth * (uint64_t)sourceHeight;
    NSDictionary *result = @{
        @"source": @"local_apple_vision",
        @"recognition_mode": effectiveFast ? @"fast" : @"accurate",
        @"frame": @{
            @"source_pixel_width": @(sourceWidth),
            @"source_pixel_height": @(sourceHeight),
            @"analyzed_pixel_width": @(analyzedWidth),
            @"analyzed_pixel_height": @(analyzedHeight),
            @"point_width": @(image.size.width),
            @"point_height": @(image.size.height),
            @"display_scale": @(image.scale),
            @"orientation": @"up",
            @"crop": @{@"x": @0, @"y": @0, @"width": @(sourceWidth), @"height": @(sourceHeight)}
        },
        @"metrics": @{
            @"latency_ms": @(MAX(0, latencyMs)),
            @"input_pixels": @(inputPixels),
            @"region_count": @(temporaryObservations.count),
            @"memory_bytes": @(residentDelta),
            @"memory_measurement": @"process_resident_delta"
        },
        @"temporary_observations": temporaryObservations
    };
    OCR_LOG(@"local visual recognition complete mode=%@ regions=%lu latency_ms=%ld", recognitionMode, (unsigned long)temporaryObservations.count, (long)MAX(0, latencyMs));
    return result;
}

@end
