// Host dependency doubles. Production method bodies are inserted by the test
// runner unchanged; no iOS frameworks, transport, or device are linked here.
#import <Foundation/Foundation.h>
#import "AccessibilityManager.h"
#import "MCPAXQueryContext.h"

static NSUInteger bootstrapCalls;
static NSUInteger voiceOverCalls;
static NSUInteger mutationCalls;
static NSDictionary *MCPAXActivateCurrentProcessAXUIClientBootstrap(BOOL force, NSString *reason) {
    bootstrapCalls++;
    mutationCalls++;
    return @{@"ok": @NO};
}
static const BOOL MCPEnableAXUIClientBootstrap = YES;

@interface ProbeResolver : NSObject
@property (nonatomic) NSUInteger calls;
@property (nonatomic, copy) NSString *mode;
- (MCPAXQueryContext *)frontmostContext;
@end
@implementation ProbeResolver
- (MCPAXQueryContext *)frontmostContext {
    self.calls++;
    if ([self.mode isEqualToString:@"no_context"]) return nil;
    if ([self.mode isEqualToString:@"context_exception"]) {
        [NSException raise:@"Synthetic" format:@"fixture-private-error"];
    }
    MCPAXQueryContext *context = [MCPAXQueryContext new];
    context.pid = 123;
    context.bundleId = @"example.fixture";
    return context;
}
@end

@interface AccessibilityManager ()
@property (nonatomic, copy) NSString *probeMode;
@property (nonatomic, copy) NSDictionary *probePayload;
@property (nonatomic) NSUInteger readCalls;
@property (nonatomic) NSUInteger bootstrapPolicyCalls;
@property (nonatomic) NSUInteger secondaryContextCalls;
- (NSDictionary *)activateVoiceOverRuntimeForContext:(MCPAXQueryContext *)context reason:(NSString *)reason;
- (BOOL)shouldAttemptAXUIClientBootstrapForContext:(MCPAXQueryContext *)context;
- (NSDictionary *)compactPayloadForContext:(MCPAXQueryContext *)context
                              maxElements:(NSInteger)maxElements visibleOnly:(BOOL)visibleOnly
                            clickableOnly:(BOOL)clickableOnly includeSemanticState:(BOOL)includeSemanticState
               includeSemanticDiagnostics:(BOOL)includeSemanticDiagnostics
                      expectedValueSHA256:(NSString *)expectedValueSHA256 error:(NSString **)error;
- (void)refreshQueryContext:(MCPAXQueryContext *)target fromContext:(MCPAXQueryContext *)source;
- (void)drain;
- (NSUInteger)contextCalls;
@end

static AccessibilityManager *probeManager;
@implementation AccessibilityManager {
    dispatch_queue_t _axQueue;
    ProbeResolver *_contextResolver;
}
+ (instancetype)sharedInstance { return probeManager; }
- (instancetype)init {
    if ((self = [super init])) {
        _axQueue = dispatch_queue_create("test52.host", DISPATCH_QUEUE_SERIAL);
        _contextResolver = [ProbeResolver new];
    }
    return self;
}
- (void)drain { dispatch_sync(_axQueue, ^{}); }
- (NSUInteger)contextCalls { return _contextResolver.calls; }
- (void)setProbeMode:(NSString *)mode {
    _probeMode = [mode copy];
    _contextResolver.mode = mode;
}
- (NSDictionary *)frontmostApplicationInfo {
    self.secondaryContextCalls++;
    return @{};
}
- (void)getElementAtPoint:(CGPoint)point completion:(void (^)(NSDictionary *, NSString *))completion {
    [NSException raise:@"UnexpectedRead" format:@"point fallback is outside the diagnostic route"];
}
- (BOOL)shouldAttemptAXUIClientBootstrapForContext:(MCPAXQueryContext *)context {
    self.bootstrapPolicyCalls++;
    return YES;
}
- (void)refreshQueryContext:(MCPAXQueryContext *)target fromContext:(MCPAXQueryContext *)source {}
- (NSDictionary *)compactPayloadForContext:(MCPAXQueryContext *)context
                              maxElements:(NSInteger)maxElements visibleOnly:(BOOL)visibleOnly
                            clickableOnly:(BOOL)clickableOnly includeSemanticState:(BOOL)includeSemanticState
               includeSemanticDiagnostics:(BOOL)includeSemanticDiagnostics
                      expectedValueSHA256:(NSString *)expectedValueSHA256 error:(NSString **)error {
    self.readCalls++;
    if ([self.probeMode isEqualToString:@"exception"]) {
        [NSException raise:@"Synthetic" format:@"fixture-private-error"];
    }
    if ([self.probeMode isEqualToString:@"timeout"]) [NSThread sleepForTimeInterval:10.2];
    if ([self.probeMode isEqualToString:@"fail"] ||
        ([self.probeMode isEqualToString:@"retry_success"] && self.readCalls == 1)) {
        if (error) *error = @"fixture-private-error";
        return nil;
    }
    if ([self.probeMode isEqualToString:@"partial_error"] && error) *error = @"fixture-private-error";
    return self.probePayload;
}
// INSERT_MANAGER_METHODS
@end

@interface TracedAccessibilityManager : AccessibilityManager
@end
@implementation TracedAccessibilityManager
- (NSDictionary *)activateVoiceOverRuntimeForContext:(MCPAXQueryContext *)context reason:(NSString *)reason {
    voiceOverCalls++;
    return [super activateVoiceOverRuntimeForContext:context reason:reason];
}
@end

// INSERT_SERVER_HELPERS
// Geometry formatting is a pure stub here; it does not dispatch a tap.
static NSDictionary *MCPCenterTapPointForElement(NSDictionary *element) { return @{@"x": @1, @"y": @1}; }

@interface ProbeServer : NSObject
- (NSDictionary *)executeGetUIElements:(id)reqId args:(NSDictionary *)args;
- (NSDictionary *)mcpError:(id)reqId code:(NSInteger)code message:(NSString *)message;
- (NSDictionary *)mcpSuccess:(id)reqId structuredContent:(NSDictionary *)payload;
- (NSDictionary *)mcpSuccess:(id)reqId structuredContent:(NSDictionary *)payload isError:(BOOL)isError;
@end
@implementation ProbeServer
- (NSDictionary *)mcpError:(id)reqId code:(NSInteger)code message:(NSString *)message {
    return @{@"isError": @YES, @"code": @(code), @"message": message ?: @""};
}
- (NSDictionary *)mcpSuccess:(id)reqId structuredContent:(NSDictionary *)payload {
    return [self mcpSuccess:reqId structuredContent:payload isError:NO];
}
- (NSDictionary *)mcpSuccess:(id)reqId structuredContent:(NSDictionary *)payload isError:(BOOL)isError {
    return @{@"isError": @(isError), @"structuredContent": payload};
}
// INSERT_SERVER_METHODS
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        NSData *input = [[NSString stringWithUTF8String:argv[1]] dataUsingEncoding:NSUTF8StringEncoding];
        NSDictionary *fixture = [NSJSONSerialization JSONObjectWithData:input options:0 error:NULL];
        probeManager = [TracedAccessibilityManager new];
        probeManager.probeMode = fixture[@"mode"];
        probeManager.probePayload = fixture[@"payload"];
        ProbeServer *server = [ProbeServer new];
        NSMutableArray *results = [NSMutableArray array];
        NSArray *requests = fixture[@"requests"] ?: @[fixture[@"args"]];
        BOOL concurrent = [fixture[@"concurrent"] boolValue];
        void (^runRequest)(NSDictionary *) = ^(NSDictionary *args) {
            NSUInteger readsBefore = concurrent ? 0 : probeManager.readCalls;
            NSUInteger bootstrapBefore = concurrent ? 0 : bootstrapCalls;
            __block NSDictionary *response;
            if ([fixture[@"native_call"] boolValue] || [fixture[@"legacy_call"] boolValue]) {
                dispatch_semaphore_t sem = dispatch_semaphore_create(0);
                void (^completion)(NSDictionary *, NSString *) = ^(NSDictionary *payload, NSString *error) {
                    response = @{@"isError": @(payload == nil), @"structuredContent": payload ?: @{}, @"error": error ?: @""};
                    dispatch_semaphore_signal(sem);
                };
                if ([fixture[@"legacy_call"] boolValue]) {
                    [probeManager getCompactUIElementsWithMaxElements:8 visibleOnly:NO clickableOnly:NO
                        includeSemanticState:YES includeSemanticDiagnostics:YES
                        expectedValueSHA256:nil completion:completion];
                } else {
                    [probeManager getCompactUIElementsWithMaxElements:8 visibleOnly:NO clickableOnly:NO
                        includeSemanticState:[args[@"include_semantic_state"] boolValue]
                        includeSemanticDiagnostics:[args[@"include_semantic_diagnostics"] boolValue]
                        expectedValueSHA256:args[@"semantic_expected_value_sha256"]
                        noBootstrapReadOnly:YES completion:completion];
                }
                if (dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 15 * NSEC_PER_SEC))) abort();
            } else {
                response = [server executeGetUIElements:@1 args:args];
            }
            [probeManager drain];
            @synchronized (results) {
                [results addObject:@{@"response": response,
                    @"reads": @(concurrent ? 0 : probeManager.readCalls - readsBefore),
                    @"bootstrap": @(concurrent ? 0 : bootstrapCalls - bootstrapBefore)}];
            }
        };
        if (concurrent) {
            dispatch_group_t group = dispatch_group_create();
            for (NSDictionary *args in requests) {
                dispatch_group_async(group, dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{ runRequest(args); });
            }
            dispatch_group_wait(group, DISPATCH_TIME_FOREVER);
        } else {
            for (NSDictionary *args in requests) runRequest(args);
        }
        NSDictionary *result = @{@"results": results, @"read_count": @(probeManager.readCalls),
            @"bootstrap_count": @(bootstrapCalls), @"voiceover_fallback_count": @(voiceOverCalls),
            @"bootstrap_policy_count": @(probeManager.bootstrapPolicyCalls),
            @"mutation_count": @(mutationCalls), @"context_count": @([probeManager contextCalls]),
            @"secondary_context_count": @(probeManager.secondaryContextCalls)};
        NSData *output = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:NULL];
        fwrite(output.bytes, 1, output.length, stdout);
        putchar('\n');
    }
    return 0;
}
