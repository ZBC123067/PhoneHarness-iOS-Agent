/*
 * mcp-logreader: unified system log reader for ios-mcp
 *
 * Connects to diagnosticd's live event stream (the same mechanism Console.app /
 * `log stream` use over USB) via the private OSLogEventLiveStream class in
 * LoggingSupport.framework. Requires the com.apple.private.logging.stream entitlement
 * (fake-signed at build time), NOT root — so the MCP server can spawn this as mobile.
 *
 * Usage:
 *   mcp-logreader [--process NAME] [--level all|error|fault] [--seconds N] [--max-lines N]
 *
 * Output: one JSON object per line (NDJSON) on stdout, then a final summary line:
 *   {"process":"wifid","pid":318,"subsystem":"...","category":"...","level":"...","message":"...","date":"..."}
 *   {"_summary":true,"count":N,"truncated":bool}
 *
 * This is a live stream: it captures events arriving during the capture window, not
 * historical logs. Stops after --seconds or once --max-lines events are emitted.
 */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import <dlfcn.h>

static NSString *MCPLogReaderJSONString(NSString *s) {
    if (![s isKindOfClass:[NSString class]] || s.length == 0) return @"\"\"";
    NSData *d = [NSJSONSerialization dataWithJSONObject:@[s] options:0 error:nil];
    if (!d) return @"\"\"";
    NSString *arr = [[NSString alloc] initWithData:d encoding:NSUTF8StringEncoding];
    // arr is ["..."]; strip the surrounding brackets to get the bare quoted string.
    if (arr.length >= 2) return [arr substringWithRange:NSMakeRange(1, arr.length - 2)];
    return @"\"\"";
}

static NSString *MCPLogLevelString(unsigned long long logType) {
    // OSLogEntryLogLevel: 0 undefined,1 debug,2 info,16 error,17 fault (varies); map common ones.
    switch (logType) {
        case 0x00: return @"notice";
        case 0x01: return @"info";
        case 0x02: return @"debug";
        case 0x10: return @"error";
        case 0x11: return @"fault";
        default: return @"default";
    }
}

int main(int argc, char *argv[]) {
    @autoreleasepool {
        NSString *processFilter = nil;
        NSString *level = @"all";
        double seconds = 5.0;
        long maxLines = 500;

        for (int i = 1; i < argc; i++) {
            NSString *a = [NSString stringWithUTF8String:argv[i]];
            if ([a isEqualToString:@"--process"] && i + 1 < argc) {
                processFilter = [NSString stringWithUTF8String:argv[++i]];
            } else if ([a isEqualToString:@"--level"] && i + 1 < argc) {
                level = [NSString stringWithUTF8String:argv[++i]];
            } else if ([a isEqualToString:@"--seconds"] && i + 1 < argc) {
                seconds = atof(argv[++i]);
            } else if ([a isEqualToString:@"--max-lines"] && i + 1 < argc) {
                maxLines = atol(argv[++i]);
            }
        }
        if (seconds <= 0) seconds = 5.0;
        if (seconds > 60) seconds = 60;
        if (maxLines <= 0) maxLines = 500;
        if (maxLines > 5000) maxLines = 5000;

        void *h = dlopen("/System/Library/PrivateFrameworks/LoggingSupport.framework/LoggingSupport", RTLD_NOW);
        if (!h) {
            fprintf(stderr, "{\"_error\":\"cannot load LoggingSupport: %s\"}\n", dlerror() ?: "?");
            return 2;
        }

        Class LiveStream = NSClassFromString(@"OSLogEventLiveStream");
        if (!LiveStream) {
            fprintf(stderr, "{\"_error\":\"OSLogEventLiveStream unavailable\"}\n");
            return 3;
        }

        id stream = [[LiveStream alloc] init];
        if (!stream) {
            fprintf(stderr, "{\"_error\":\"cannot create live stream (entitlement com.apple.private.logging.stream required)\"}\n");
            return 4;
        }

        if (processFilter.length) {
            NSPredicate *p = [NSPredicate predicateWithFormat:@"process CONTAINS[c] %@", processFilter];
            ((void(*)(id,SEL,id))objc_msgSend)(stream, sel_registerName("setFilterPredicate:"), p);
        }

        __block long count = 0;
        __block BOOL truncated = NO;
        BOOL wantError = [level isEqualToString:@"error"];
        BOOL wantFault = [level isEqualToString:@"fault"];

        void (^handler)(id) = ^(id ev) {
            if (count >= maxLines) { truncated = YES; return; }

            unsigned long long logType = 0;
            if ([ev respondsToSelector:@selector(logType)]) {
                logType = ((unsigned long long(*)(id,SEL))objc_msgSend)(ev, @selector(logType));
            }
            if (wantError && logType != 0x10 && logType != 0x11) return;
            if (wantFault && logType != 0x11) return;

            int pid = 0;
            if ([ev respondsToSelector:@selector(processIdentifier)]) {
                pid = ((int(*)(id,SEL))objc_msgSend)(ev, @selector(processIdentifier));
            }
            NSString *proc = ((id(*)(id,SEL))objc_msgSend)(ev, sel_registerName("process"));
            NSString *msg = ((id(*)(id,SEL))objc_msgSend)(ev, sel_registerName("composedMessage"));
            NSString *sub = ((id(*)(id,SEL))objc_msgSend)(ev, sel_registerName("subsystem"));
            NSString *cat = ((id(*)(id,SEL))objc_msgSend)(ev, sel_registerName("category"));
            NSDate *date = ((id(*)(id,SEL))objc_msgSend)(ev, sel_registerName("date"));

            NSString *dateStr = [date isKindOfClass:[NSDate class]] ? date.description : @"";

            printf("{\"process\":%s,\"pid\":%d,\"subsystem\":%s,\"category\":%s,\"level\":\"%s\",\"date\":%s,\"message\":%s}\n",
                   MCPLogReaderJSONString(proc).UTF8String,
                   pid,
                   MCPLogReaderJSONString(sub).UTF8String,
                   MCPLogReaderJSONString(cat).UTF8String,
                   MCPLogLevelString(logType).UTF8String,
                   MCPLogReaderJSONString(dateStr).UTF8String,
                   MCPLogReaderJSONString(msg).UTF8String);
            count++;
            if (count % 20 == 0) fflush(stdout);
        };

        ((void(*)(id,SEL,id))objc_msgSend)(stream, sel_registerName("setEventHandler:"), handler);
        ((void(*)(id,SEL))objc_msgSend)(stream, sel_registerName("activate"));

        [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:seconds]];

        if ([stream respondsToSelector:@selector(invalidate)]) {
            ((void(*)(id,SEL))objc_msgSend)(stream, sel_registerName("invalidate"));
        }

        printf("{\"_summary\":true,\"count\":%ld,\"truncated\":%s}\n", count, truncated ? "true" : "false");
        fflush(stdout);
        return 0;
    }
}
