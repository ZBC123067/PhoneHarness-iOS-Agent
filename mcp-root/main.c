/*
 * mcp-root: setuid root helper for ios-mcp
 * Allows the MCP server (running as mobile) to execute commands as root.
 * Must be installed with setuid bit: chmod 4755 mcp-root
 */
#include <errno.h>
#include <ctype.h>
#include <fcntl.h>
#include <limits.h>
#include <spawn.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#ifdef MCP_ROOTHIDE
#include <roothide.h>
#endif

extern char **environ;

typedef enum {
    MCP_ALLOWED_COMMAND_NONE = 0,
    MCP_ALLOWED_COMMAND_ROOTHELPER,
    MCP_ALLOWED_COMMAND_APPINST,
    MCP_ALLOWED_COMMAND_LDID,
    MCP_ALLOWED_COMMAND_CHMOD,
    MCP_ALLOWED_COMMAND_LAUNCHCTL,
    MCP_ALLOWED_COMMAND_ID,
    MCP_ALLOWED_COMMAND_DPKG,
} MCPAllowedCommand;

static void print_usage(const char *program) {
    fprintf(stderr, "Usage: %s <command> [args...]\n", program);
    fprintf(stderr, "Allowed commands:\n");
    fprintf(stderr, "  /usr/bin/mcp-roothelper <ipa>\n");
    fprintf(stderr, "  /usr/bin/mcp-appinst <ipa>\n");
    fprintf(stderr, "  /usr/bin/mcp-ldid -S[entitlements] <app-container-target>\n");
    fprintf(stderr, "  /bin/chmod 0644|0755 <app-container-path>...\n");
    fprintf(stderr, "  /bin/launchctl kickstart -k <approved-accessibility-service>\n");
    fprintf(stderr, "  /usr/bin/id\n");
    fprintf(stderr, "  /usr/bin/dpkg -i|--install|--unpack [safe dpkg options] <absolute .deb path>...\n");
    fprintf(stderr, "  /usr/bin/dpkg -s|--status|-r|--remove|--purge <package-id>\n");
}

static const char *resolve_command_path(const char *path) {
    if (!path || path[0] == '\0') {
        return path;
    }

#ifdef MCP_ROOTHIDE
    const char *jbPath = jbroot(path);
    if (jbPath && access(jbPath, X_OK) == 0) {
        return jbPath;
    }

    const char *rootfsPath = rootfs(path);
    if (rootfsPath && access(rootfsPath, X_OK) == 0) {
        return rootfsPath;
    }
#endif

#ifndef MCP_ROOTHIDE
    if (path[0] == '/' && strncmp(path, "/var/jb/", 8) != 0) {
        static char rootlessPaths[4][PATH_MAX];
        static unsigned int rootlessPathIndex = 0;
        char *candidate = rootlessPaths[rootlessPathIndex++ % 4];
        int written = snprintf(candidate, PATH_MAX, "/var/jb%s", path);
        if (written > 0 && written < PATH_MAX && access(candidate, X_OK) == 0) {
            return candidate;
        }
    }
#endif

    return path;
}

static int canonicalize_existing_path(const char *path, char *buffer, size_t size) {
    if (!path || !buffer || size == 0) {
        return 0;
    }

    if (!realpath(path, buffer)) {
        return 0;
    }

    return 1;
}

static int canonicalize_existing_bootstrap_path(const char *path, char *buffer, size_t size) {
    if (canonicalize_existing_path(path, buffer, size)) {
        return 1;
    }

#ifdef MCP_ROOTHIDE
    const char *systemPath = jbroot(path);
    if (systemPath && systemPath[0] != '\0' &&
        canonicalize_existing_path(systemPath, buffer, size)) {
        return 1;
    }
#endif

    return 0;
}

static int paths_match(const char *lhs, const char *rhs) {
    if (!lhs || !rhs) {
        return 0;
    }

    char lhsResolved[PATH_MAX];
    char rhsResolved[PATH_MAX];
    if (canonicalize_existing_path(lhs, lhsResolved, sizeof(lhsResolved)) &&
        canonicalize_existing_path(rhs, rhsResolved, sizeof(rhsResolved))) {
        return strcmp(lhsResolved, rhsResolved) == 0;
    }

    return strcmp(lhs, rhs) == 0;
}

static int path_has_prefix(const char *path, const char *prefix) {
    size_t prefixLen;

    if (!path || !prefix) {
        return 0;
    }

    prefixLen = strlen(prefix);
    if (strncmp(path, prefix, prefixLen) != 0) {
        return 0;
    }

    return path[prefixLen] == '\0' || path[prefixLen] == '/';
}

static int path_is_allowed_chmod_target(const char *path) {
    static const char *const rawPrefixes[] = {
        "/var/containers/Bundle/Application",
        "/private/var/containers/Bundle/Application",
    };
    char resolvedPath[PATH_MAX];
    size_t i;

    if (!canonicalize_existing_path(path, resolvedPath, sizeof(resolvedPath))) {
        return 0;
    }

    for (i = 0; i < sizeof(rawPrefixes) / sizeof(rawPrefixes[0]); i++) {
        const char *prefix = rawPrefixes[i];

        if (path_has_prefix(resolvedPath, prefix)) {
            return 1;
        }

#ifdef MCP_ROOTHIDE
        {
            char resolvedPrefix[PATH_MAX];
            const char *rootfsPrefix = rootfs(prefix);
            if (rootfsPrefix && rootfsPrefix[0] != '\0' &&
                canonicalize_existing_path(rootfsPrefix, resolvedPrefix, sizeof(resolvedPrefix)) &&
                path_has_prefix(resolvedPath, resolvedPrefix)) {
                return 1;
            }
        }
#endif
    }

    return 0;
}

/* AppManager.m fakesign issues exactly one privileged ldid shape:
 *   mcp-ldid -S <target>                 (flag with no suffix)
 *   mcp-ldid -S<entitlements> <target>   (flag suffix is an absolute path that
 *                                         ldid only reads)
 * The signing target is the only root write destination, so it must resolve
 * inside an application bundle container. Anything else fails closed before
 * setuid(0). */
static int validate_ldid_arguments(int argc, char *argv[]) {
    const char *flag;
    const char *target;

    if (argc != 4) {
        fprintf(stderr, "mcp-ldid requires exactly: mcp-ldid -S[entitlements] <target>\n");
        return 0;
    }

    flag = argv[2];
    target = argv[3];

    if (strncmp(flag, "-S", 2) != 0) {
        fprintf(stderr, "mcp-ldid flag must start with -S\n");
        return 0;
    }
    if (flag[2] != '\0' && flag[2] != '/') {
        fprintf(stderr, "mcp-ldid -S entitlements suffix must be an absolute path\n");
        return 0;
    }
    if (target[0] != '/') {
        fprintf(stderr, "mcp-ldid target must be an absolute path\n");
        return 0;
    }
    if (!path_is_allowed_chmod_target(target)) {
        fprintf(stderr, "mcp-ldid target must be inside an application bundle container\n");
        return 0;
    }
    return 1;
}

static int path_has_deb_extension(const char *path) {
    size_t len;

    if (!path) {
        return 0;
    }

    len = strlen(path);
    if (len < 4) {
        return 0;
    }

    return strcasecmp(path + len - 4, ".deb") == 0;
}

static int path_is_deb_file(const char *path) {
    char resolvedPath[PATH_MAX];
    struct stat st;
    int fd;
    char header[8];
    ssize_t bytesRead;

    if (!path || path[0] != '/') {
        fprintf(stderr, "dpkg package path must be absolute: %s\n", path ? path : "(null)");
        return 0;
    }

    if (!path_has_deb_extension(path)) {
        fprintf(stderr, "dpkg package path must end with .deb: %s\n", path);
        return 0;
    }

    if (!canonicalize_existing_bootstrap_path(path, resolvedPath, sizeof(resolvedPath))) {
        fprintf(stderr, "dpkg package does not exist: %s\n", path);
        return 0;
    }

    if (stat(resolvedPath, &st) != 0 || !S_ISREG(st.st_mode)) {
        fprintf(stderr, "dpkg package is not a regular file: %s\n", path);
        return 0;
    }

    fd = open(resolvedPath, O_RDONLY);
    if (fd < 0) {
        fprintf(stderr, "cannot open dpkg package: %s\n", path);
        return 0;
    }

    bytesRead = read(fd, header, sizeof(header));
    close(fd);
    if (bytesRead != (ssize_t)sizeof(header) || memcmp(header, "!<arch>\n", sizeof(header)) != 0) {
        fprintf(stderr, "dpkg package is not a deb archive: %s\n", path);
        return 0;
    }

    return 1;
}

static int is_valid_dpkg_package_id(const char *package_id) {
    size_t len;
    size_t i;

    if (!package_id) {
        return 0;
    }

    len = strlen(package_id);
    if (len == 0 || len > 128) {
        return 0;
    }

    if (!isalnum((unsigned char)package_id[0])) {
        return 0;
    }

    for (i = 1; i < len; i++) {
        unsigned char ch = (unsigned char)package_id[i];
        if (!isalnum(ch) && ch != '+' && ch != '-' && ch != '.') {
            return 0;
        }
    }

    return 1;
}

static int validate_chmod_arguments(int argc, char *argv[]) {
    int i;

    if (argc < 4) {
        fprintf(stderr, "chmod requires a mode and at least one target path\n");
        return 0;
    }

    if (strcmp(argv[2], "0644") != 0 && strcmp(argv[2], "0755") != 0) {
        fprintf(stderr, "chmod mode %s is not permitted\n", argv[2]);
        return 0;
    }

    for (i = 3; i < argc; i++) {
        if (!argv[i] || argv[i][0] == '\0' || argv[i][0] == '-') {
            fprintf(stderr, "invalid chmod target: %s\n", argv[i] ? argv[i] : "(null)");
            return 0;
        }

        if (!path_is_allowed_chmod_target(argv[i])) {
            fprintf(stderr, "chmod target is outside the app container: %s\n", argv[i]);
            return 0;
        }
    }

    return 1;
}

static int validate_launchctl_arguments(int argc, char *argv[]) {
    if (argc != 5) {
        fprintf(stderr, "launchctl usage is restricted to kickstart -k approved accessibility services\n");
        return 0;
    }

    if (strcmp(argv[2], "kickstart") != 0 || strcmp(argv[3], "-k") != 0) {
        fprintf(stderr, "launchctl arguments are not permitted\n");
        return 0;
    }

    if (strcmp(argv[4], "system/com.apple.accessibility.AccessibilityUIServer") != 0 &&
        strcmp(argv[4], "system/com.apple.VoiceOverTouch") != 0) {
        fprintf(stderr, "launchctl target is not permitted: %s\n", argv[4] ? argv[4] : "(null)");
        return 0;
    }

    return 1;
}

static int is_allowed_dpkg_option(const char *arg) {
    static const char *const allowedOptions[] = {
        "--force-all",
        "--force-depends",
        "--force-overwrite",
        "--force-confnew",
        "--force-confold",
        "--force-confdef",
        "--force-unsafe-io",
        "--no-triggers",
    };
    size_t i;

    if (!arg) {
        return 0;
    }

    for (i = 0; i < sizeof(allowedOptions) / sizeof(allowedOptions[0]); i++) {
        if (strcmp(arg, allowedOptions[i]) == 0) {
            return 1;
        }
    }

    return 0;
}

static int validate_id_arguments(int argc, char *argv[]) {
    (void)argv;

    if (argc != 2) {
        fprintf(stderr, "id usage is restricted to id with no arguments\n");
        return 0;
    }

    return 1;
}

typedef enum {
    MCP_DPKG_OPERATION_NONE = 0,
    MCP_DPKG_OPERATION_INSTALL,
    MCP_DPKG_OPERATION_STATUS,
    MCP_DPKG_OPERATION_REMOVE,
} MCPDpkgOperation;

static int validate_dpkg_arguments(int argc, char *argv[]) {
    int i;
    MCPDpkgOperation operation = MCP_DPKG_OPERATION_NONE;
    int packageCount = 0;
    int sawInstallOption = 0;

    if (argc < 4) {
        fprintf(stderr, "dpkg usage is restricted to install/status/remove operations\n");
        return 0;
    }

    for (i = 2; i < argc; i++) {
        const char *arg = argv[i];

        if (!arg || arg[0] == '\0') {
            fprintf(stderr, "invalid empty dpkg argument\n");
            return 0;
        }

        if (strcmp(arg, "-i") == 0 || strcmp(arg, "--install") == 0 || strcmp(arg, "--unpack") == 0) {
            if (operation != MCP_DPKG_OPERATION_NONE) {
                fprintf(stderr, "dpkg operation may only be specified once\n");
                return 0;
            }
            operation = MCP_DPKG_OPERATION_INSTALL;
            continue;
        }

        if (strcmp(arg, "-s") == 0 || strcmp(arg, "--status") == 0) {
            if (operation != MCP_DPKG_OPERATION_NONE) {
                fprintf(stderr, "dpkg operation may only be specified once\n");
                return 0;
            }
            if (sawInstallOption) {
                fprintf(stderr, "dpkg install options are not permitted for status operations\n");
                return 0;
            }
            operation = MCP_DPKG_OPERATION_STATUS;
            continue;
        }

        if (strcmp(arg, "-r") == 0 || strcmp(arg, "--remove") == 0 || strcmp(arg, "--purge") == 0) {
            if (operation != MCP_DPKG_OPERATION_NONE) {
                fprintf(stderr, "dpkg operation may only be specified once\n");
                return 0;
            }
            if (sawInstallOption) {
                fprintf(stderr, "dpkg install options are not permitted for remove operations\n");
                return 0;
            }
            operation = MCP_DPKG_OPERATION_REMOVE;
            continue;
        }

        if (arg[0] == '-') {
            if (!is_allowed_dpkg_option(arg)) {
                fprintf(stderr, "dpkg option is not permitted: %s\n", arg);
                return 0;
            }
            if (operation == MCP_DPKG_OPERATION_STATUS || operation == MCP_DPKG_OPERATION_REMOVE) {
                fprintf(stderr, "dpkg option is only permitted for install operations: %s\n", arg);
                return 0;
            }
            sawInstallOption = 1;
            continue;
        }

        if (operation == MCP_DPKG_OPERATION_NONE) {
            fprintf(stderr, "dpkg package paths or ids must follow an allowed operation\n");
            return 0;
        }

        if (operation == MCP_DPKG_OPERATION_INSTALL) {
            if (!path_is_deb_file(arg)) {
                return 0;
            }
        } else {
            if (!is_valid_dpkg_package_id(arg)) {
                fprintf(stderr, "dpkg package id is not permitted: %s\n", arg);
                return 0;
            }
        }
        packageCount++;
    }

    if (operation == MCP_DPKG_OPERATION_NONE || packageCount == 0) {
        fprintf(stderr, "dpkg requires an allowed operation and package argument\n");
        return 0;
    }

    if (sawInstallOption && operation != MCP_DPKG_OPERATION_INSTALL) {
        fprintf(stderr, "dpkg install options require an install operation\n");
        return 0;
    }

    if (operation != MCP_DPKG_OPERATION_INSTALL && packageCount != 1) {
        fprintf(stderr, "dpkg status/remove operations require exactly one package id\n");
        return 0;
    }

    return 1;
}

static MCPAllowedCommand classify_allowed_command(const char *command_path) {
    struct {
        const char *logical_path;
        MCPAllowedCommand command;
    } candidates[] = {
        {"/usr/bin/mcp-roothelper", MCP_ALLOWED_COMMAND_ROOTHELPER},
        {"/usr/bin/mcp-appinst", MCP_ALLOWED_COMMAND_APPINST},
        {"/usr/bin/mcp-ldid", MCP_ALLOWED_COMMAND_LDID},
        {"/bin/chmod", MCP_ALLOWED_COMMAND_CHMOD},
        {"/usr/bin/chmod", MCP_ALLOWED_COMMAND_CHMOD},
        {"/bin/launchctl", MCP_ALLOWED_COMMAND_LAUNCHCTL},
        {"/usr/bin/launchctl", MCP_ALLOWED_COMMAND_LAUNCHCTL},
        {"/bin/id", MCP_ALLOWED_COMMAND_ID},
        {"/usr/bin/id", MCP_ALLOWED_COMMAND_ID},
        {"/var/jb/bin/id", MCP_ALLOWED_COMMAND_ID},
        {"/var/jb/usr/bin/id", MCP_ALLOWED_COMMAND_ID},
        {"/usr/bin/dpkg", MCP_ALLOWED_COMMAND_DPKG},
        {"/var/jb/usr/bin/dpkg", MCP_ALLOWED_COMMAND_DPKG},
    };
    size_t i;

    for (i = 0; i < sizeof(candidates) / sizeof(candidates[0]); i++) {
        const char *allowedPath = resolve_command_path(candidates[i].logical_path);
        if (paths_match(command_path, allowedPath)) {
            return candidates[i].command;
        }
    }

    return MCP_ALLOWED_COMMAND_NONE;
}

int main(int argc, char *argv[]) {
    MCPAllowedCommand allowedCommand;
    const char *resolved_command_path;
    char command_path[PATH_MAX];

    if (argc < 2) {
        print_usage(argv[0]);
        return 1;
    }

    if (strcmp(argv[1], "-h") == 0 || strcmp(argv[1], "--help") == 0) {
        print_usage(argv[0]);
        return 0;
    }

    resolved_command_path = resolve_command_path(argv[1]);
    if (!resolved_command_path || strlen(resolved_command_path) >= sizeof(command_path)) {
        fprintf(stderr, "Command path is invalid or too long: %s\n", argv[1] ? argv[1] : "(null)");
        return 126;
    }
    snprintf(command_path, sizeof(command_path), "%s", resolved_command_path);
    allowedCommand = classify_allowed_command(command_path);
    if (allowedCommand == MCP_ALLOWED_COMMAND_NONE) {
        fprintf(stderr, "Command is not permitted: %s\n", argv[1]);
        return 126;
    }

    if (allowedCommand == MCP_ALLOWED_COMMAND_CHMOD && !validate_chmod_arguments(argc, argv)) {
        return 126;
    }
    if (allowedCommand == MCP_ALLOWED_COMMAND_LDID && !validate_ldid_arguments(argc, argv)) {
        return 126;
    }
    if (allowedCommand == MCP_ALLOWED_COMMAND_LAUNCHCTL && !validate_launchctl_arguments(argc, argv)) {
        return 126;
    }
    if (allowedCommand == MCP_ALLOWED_COMMAND_ID && !validate_id_arguments(argc, argv)) {
        return 126;
    }
    if (allowedCommand == MCP_ALLOWED_COMMAND_DPKG && !validate_dpkg_arguments(argc, argv)) {
        return 126;
    }

    if (setgid(0) != 0) {
        fprintf(stderr, "setgid(0) failed: %s\n", strerror(errno));
        return 111;
    }

    if (setuid(0) != 0) {
        fprintf(stderr, "setuid(0) failed: %s\n", strerror(errno));
        return 111;
    }

    pid_t pid = 0;
    argv[1] = command_path;
    int spawnStatus = posix_spawn(&pid, command_path, NULL, NULL, &argv[1], environ);
    if (spawnStatus != 0) {
        fprintf(stderr, "posix_spawn(%s) failed: %s\n", command_path, strerror(spawnStatus));
        return spawnStatus == ENOENT ? 127 : spawnStatus;
    }

    int status = 0;
    if (waitpid(pid, &status, 0) < 0) {
        fprintf(stderr, "waitpid(%d) failed: %s\n", pid, strerror(errno));
        return 111;
    }

    if (WIFEXITED(status)) {
        return WEXITSTATUS(status);
    }

    if (WIFSIGNALED(status)) {
        return 128 + WTERMSIG(status);
    }

    fprintf(stderr, "child exited unexpectedly\n");
    return 111;
}
