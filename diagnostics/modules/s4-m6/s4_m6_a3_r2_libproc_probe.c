/*
 * Bounded, read-only libproc reality probe for S4-M6-A3-R2.
 *
 * This source intentionally carries the minimal public ABI shapes required by
 * the probe because the RootHide device toolchain does not ship libproc
 * headers. It resolves observation-only symbols at runtime, performs no
 * process/service mutation, and emits aggregate/sanitized JSON only.
 */

#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#define PH_MAX_PIDS 8192
#define PH_MAXCOMLEN 16
#define PH_PATH_BUFFER 4096
#define PH_PROC_PIDTBSDINFO 3
#define PH_PROC_PIDTASKINFO 4
#define PH_PROC_ALL_PIDS 1
#define PH_RUSAGE_INFO_V0 0

struct ph_proc_bsdinfo {
    uint32_t pbi_flags;
    uint32_t pbi_status;
    uint32_t pbi_xstatus;
    uint32_t pbi_pid;
    uint32_t pbi_ppid;
    uid_t pbi_uid;
    gid_t pbi_gid;
    uid_t pbi_ruid;
    gid_t pbi_rgid;
    uid_t pbi_svuid;
    gid_t pbi_svgid;
    uint32_t rfu_1;
    char pbi_comm[PH_MAXCOMLEN];
    char pbi_name[2 * PH_MAXCOMLEN];
    uint32_t pbi_nfiles;
    uint32_t pbi_pgid;
    uint32_t pbi_pjobc;
    uint32_t e_tdev;
    uint32_t e_tpgid;
    int32_t pbi_nice;
    uint64_t pbi_start_tvsec;
    uint64_t pbi_start_tvusec;
};

struct ph_proc_taskinfo {
    uint64_t pti_virtual_size;
    uint64_t pti_resident_size;
    uint64_t pti_total_user;
    uint64_t pti_total_system;
    uint64_t pti_threads_user;
    uint64_t pti_threads_system;
    int32_t pti_policy;
    int32_t pti_faults;
    int32_t pti_pageins;
    int32_t pti_cow_faults;
    int32_t pti_messages_sent;
    int32_t pti_messages_received;
    int32_t pti_syscalls_mach;
    int32_t pti_syscalls_unix;
    int32_t pti_csw;
    int32_t pti_threadnum;
    int32_t pti_numrunning;
    int32_t pti_priority;
};

struct ph_rusage_info_v0 {
    uint8_t ri_uuid[16];
    uint64_t ri_user_time;
    uint64_t ri_system_time;
    uint64_t ri_pkg_idle_wkups;
    uint64_t ri_interrupt_wkups;
    uint64_t ri_pageins;
    uint64_t ri_wired_size;
    uint64_t ri_resident_size;
    uint64_t ri_phys_footprint;
    uint64_t ri_proc_start_abstime;
    uint64_t ri_proc_exit_abstime;
};

typedef int (*ph_proc_listallpids_fn)(void *, int);
typedef int (*ph_proc_listpids_fn)(uint32_t, uint32_t, void *, int);
typedef int (*ph_proc_pidinfo_fn)(int, int, uint64_t, void *, int);
typedef int (*ph_proc_name_fn)(int, void *, uint32_t);
typedef int (*ph_proc_pidpath_fn)(int, void *, uint32_t);
typedef int (*ph_proc_pid_rusage_fn)(int, int, void *);

struct ph_error_counts {
    unsigned permission;
    unsigned not_found;
    unsigned invalid;
    unsigned unsupported;
    unsigned other;
};

static void ph_count_errno(struct ph_error_counts *counts, int value) {
    if (value == EPERM || value == EACCES) {
        counts->permission++;
    } else if (value == ESRCH || value == ENOENT) {
        counts->not_found++;
    } else if (value == EINVAL || value == EFAULT) {
        counts->invalid++;
#ifdef ENOTSUP
    } else if (value == ENOTSUP) {
        counts->unsupported++;
#endif
#ifdef EOPNOTSUPP
    } else if (value == EOPNOTSUPP) {
        counts->unsupported++;
#endif
    } else {
        counts->other++;
    }
}

static uint64_t ph_monotonic_ms(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) {
        return 0;
    }
    return ((uint64_t)value.tv_sec * 1000U) + ((uint64_t)value.tv_nsec / 1000000U);
}

static int ph_is_springboard(const struct ph_proc_bsdinfo *info) {
    return strncmp(info->pbi_name, "SpringBoard", sizeof(info->pbi_name)) == 0 ||
           strncmp(info->pbi_comm, "SpringBoard", sizeof(info->pbi_comm)) == 0;
}

static int ph_path_basename_is_springboard(const char *path, size_t length) {
    const char *last = path;
    size_t index;
    for (index = 0; index < length && path[index] != '\0'; index++) {
        if (path[index] == '/') {
            last = path + index + 1;
        }
    }
    return strcmp(last, "SpringBoard") == 0;
}

int main(int argc, char **argv) {
    uint64_t started_ms = ph_monotonic_ms();
    ph_proc_listallpids_fn list_all =
        (ph_proc_listallpids_fn)dlsym(RTLD_DEFAULT, "proc_listallpids");
    ph_proc_listpids_fn list_pids =
        (ph_proc_listpids_fn)dlsym(RTLD_DEFAULT, "proc_listpids");
    ph_proc_pidinfo_fn pid_info =
        (ph_proc_pidinfo_fn)dlsym(RTLD_DEFAULT, "proc_pidinfo");
    ph_proc_name_fn proc_name =
        (ph_proc_name_fn)dlsym(RTLD_DEFAULT, "proc_name");
    ph_proc_pidpath_fn pid_path =
        (ph_proc_pidpath_fn)dlsym(RTLD_DEFAULT, "proc_pidpath");
    ph_proc_pid_rusage_fn pid_rusage =
        (ph_proc_pid_rusage_fn)dlsym(RTLD_DEFAULT, "proc_pid_rusage");
    void *pidpath_audittoken = dlsym(RTLD_DEFAULT, "proc_pidpath_audittoken");
    pid_t pids[PH_MAX_PIDS];
    int listed = -1;
    int listall_result = -1;
    int listpids_bytes = -1;
    int direct_count = 0;
    int selected_pid = 0;
    uint64_t selected_start_sec = 0;
    uint64_t selected_start_usec = 0;
    unsigned bsd_success = 0;
    unsigned bsd_start_present = 0;
    unsigned bsd_distinct_start_markers = 0;
    unsigned task_success = 0;
    unsigned rusage_success = 0;
    unsigned name_success = 0;
    unsigned path_success = 0;
    unsigned control_plane_seen = 0;
    unsigned control_plane_path_supported = 0;
    unsigned start_stability_successes = 0;
    unsigned start_stability_rounds = 0;
    unsigned api_invocations = 0;
    struct ph_error_counts errors = {0, 0, 0, 0, 0};
    int index;
    int explicit_sample_pid = 0;

    if (argc == 3 && strcmp(argv[1], "--sample-pid") == 0) {
        char *end = NULL;
        long value = strtol(argv[2], &end, 10);
        if (end != argv[2] && *end == '\0' && value > 0 && value <= INT32_MAX) {
            explicit_sample_pid = (int)value;
        }
    }

    memset(pids, 0, sizeof(pids));
    if (list_all != NULL) {
        errno = 0;
        listed = list_all(pids, (int)sizeof(pids));
        listall_result = listed;
        api_invocations++;
        if (listed < 0) {
            ph_count_errno(&errors, errno);
        }
    }

    if (listed <= 0 && list_pids != NULL) {
        memset(pids, 0, sizeof(pids));
        errno = 0;
        listpids_bytes = list_pids(
            PH_PROC_ALL_PIDS,
            0,
            pids,
            (int)sizeof(pids)
        );
        api_invocations++;
        if (listpids_bytes < 0) {
            ph_count_errno(&errors, errno);
        } else {
            listed = listpids_bytes / (int)sizeof(pid_t);
        }
    }

    if (listed > PH_MAX_PIDS) {
        listed = PH_MAX_PIDS;
    }
    if (listed > 0) {
        for (index = 0; index < listed; index++) {
            if (pids[index] > 0) {
                direct_count++;
            }
        }
    }


    /* Directly prove per-PID API behavior even if inventory is unavailable. */
    if (direct_count == 0) {
        int fallback_count = 0;
        if (explicit_sample_pid > 0) {
            pids[fallback_count++] = explicit_sample_pid;
        }
        pids[fallback_count++] = getpid();
        pids[fallback_count++] = 1;
        listed = fallback_count;
    }

    if (pid_info != NULL && listed > 0) {
        uint64_t previous_start_sec = UINT64_MAX;
        uint64_t previous_start_usec = UINT64_MAX;
        for (index = 0; index < listed; index++) {
            struct ph_proc_bsdinfo bsd;
            int rc;
            if (pids[index] <= 0) {
                continue;
            }
            memset(&bsd, 0, sizeof(bsd));
            errno = 0;
            rc = pid_info(pids[index], PH_PROC_PIDTBSDINFO, 0, &bsd, (int)sizeof(bsd));
            api_invocations++;
            if (rc == (int)sizeof(bsd)) {
                bsd_success++;
                if (bsd.pbi_start_tvsec != 0 || bsd.pbi_start_tvusec != 0) {
                    bsd_start_present++;
                    if (bsd.pbi_start_tvsec != previous_start_sec ||
                        bsd.pbi_start_tvusec != previous_start_usec) {
                        bsd_distinct_start_markers++;
                        previous_start_sec = bsd.pbi_start_tvsec;
                        previous_start_usec = bsd.pbi_start_tvusec;
                    }
                    if (selected_pid == 0) {
                        selected_pid = pids[index];
                        selected_start_sec = bsd.pbi_start_tvsec;
                        selected_start_usec = bsd.pbi_start_tvusec;
                    }
                }
                if (ph_is_springboard(&bsd)) {
                    control_plane_seen = 1;
                    if (pid_path != NULL) {
                        char path[PH_PATH_BUFFER];
                        int path_rc;
                        memset(path, 0, sizeof(path));
                        errno = 0;
                        path_rc = pid_path(pids[index], path, (uint32_t)sizeof(path));
                        api_invocations++;
                        if (path_rc > 0) {
                            path_success++;
                            if (ph_path_basename_is_springboard(path, (size_t)path_rc)) {
                                control_plane_path_supported = 1;
                            }
                        } else {
                            ph_count_errno(&errors, errno);
                        }
                    }
                }
            } else {
                ph_count_errno(&errors, errno);
            }
        }
    }

    if (listed > 0) {
        unsigned bounded_samples = 0;
        for (index = 0; index < listed && bounded_samples < 32; index++) {
            int pid = pids[index];
            if (pid <= 0) {
                continue;
            }
            bounded_samples++;
            if (pid_info != NULL) {
                struct ph_proc_taskinfo task;
                int rc;
                memset(&task, 0, sizeof(task));
                errno = 0;
                rc = pid_info(pid, PH_PROC_PIDTASKINFO, 0, &task, (int)sizeof(task));
                api_invocations++;
                if (rc == (int)sizeof(task)) {
                    task_success++;
                } else {
                    ph_count_errno(&errors, errno);
                }
            }
            if (pid_rusage != NULL) {
                struct ph_rusage_info_v0 usage;
                int rc;
                memset(&usage, 0, sizeof(usage));
                errno = 0;
                rc = pid_rusage(pid, PH_RUSAGE_INFO_V0, &usage);
                api_invocations++;
                if (rc == 0) {
                    rusage_success++;
                } else {
                    ph_count_errno(&errors, errno);
                }
            }
            if (proc_name != NULL) {
                char name[128];
                int rc;
                memset(name, 0, sizeof(name));
                errno = 0;
                rc = proc_name(pid, name, (uint32_t)sizeof(name));
                api_invocations++;
                if (rc > 0) {
                    name_success++;
                } else {
                    ph_count_errno(&errors, errno);
                }
            }
            if (pid_path != NULL && !control_plane_seen) {
                char path[PH_PATH_BUFFER];
                int rc;
                memset(path, 0, sizeof(path));
                errno = 0;
                rc = pid_path(pid, path, (uint32_t)sizeof(path));
                api_invocations++;
                if (rc > 0) {
                    path_success++;
                } else {
                    ph_count_errno(&errors, errno);
                }
            }
        }
    }

    if (selected_pid > 0 && pid_info != NULL) {
        unsigned round;
        for (round = 0; round < 3; round++) {
            struct ph_proc_bsdinfo bsd;
            int rc;
            if (round > 0) {
                usleep(250000);
            }
            memset(&bsd, 0, sizeof(bsd));
            errno = 0;
            rc = pid_info(selected_pid, PH_PROC_PIDTBSDINFO, 0, &bsd, (int)sizeof(bsd));
            api_invocations++;
            start_stability_rounds++;
            if (rc == (int)sizeof(bsd) &&
                bsd.pbi_pid == (uint32_t)selected_pid &&
                bsd.pbi_start_tvsec == selected_start_sec &&
                bsd.pbi_start_tvusec == selected_start_usec) {
                start_stability_successes++;
            } else if (rc != (int)sizeof(bsd)) {
                ph_count_errno(&errors, errno);
            }
        }
    }

    printf("{");
    printf("\"schema\":\"phoneharness.s4-m6-a3-r2-libproc-probe.v1\",");
    printf("\"symbols\":{");
    printf("\"proc_listallpids\":%s,", list_all ? "true" : "false");
    printf("\"proc_listpids\":%s,", list_pids ? "true" : "false");
    printf("\"proc_pidinfo\":%s,", pid_info ? "true" : "false");
    printf("\"proc_name\":%s,", proc_name ? "true" : "false");
    printf("\"proc_pidpath\":%s,", pid_path ? "true" : "false");
    printf("\"proc_pid_rusage\":%s,", pid_rusage ? "true" : "false");
    printf("\"proc_pidpath_audittoken\":%s},", pidpath_audittoken ? "true" : "false");
    printf("\"direct_process_count\":%d,", direct_count);
    printf("\"proc_listallpids_result\":%d,", listall_result);
    printf("\"proc_listpids_bytes\":%d,", listpids_bytes);
    printf("\"proc_pidbsdinfo_success_count\":%u,", bsd_success);
    printf("\"start_time_present_count\":%u,", bsd_start_present);
    printf("\"distinct_start_marker_count\":%u,", bsd_distinct_start_markers);
    printf("\"start_time_stability_rounds\":%u,", start_stability_rounds);
    printf("\"start_time_stability_successes\":%u,", start_stability_successes);
    printf("\"proc_pidtaskinfo_success_count\":%u,", task_success);
    printf("\"proc_pid_rusage_success_count\":%u,", rusage_success);
    printf("\"proc_name_success_count\":%u,", name_success);
    printf("\"proc_pidpath_success_count\":%u,", path_success);
    printf("\"control_plane_seen\":%s,", control_plane_seen ? "true" : "false");
    printf("\"control_plane_executable_basename_match\":%s,",
           control_plane_path_supported ? "true" : "false");
    printf("\"sampled_resource_process_count\":%u,", direct_count == 0 ? (explicit_sample_pid > 0 ? 3U : 2U) : (direct_count < 32 ? (unsigned)direct_count : 32U));
    printf("\"api_invocation_count\":%u,", api_invocations);
    printf("\"elapsed_ms\":%llu,", (unsigned long long)(ph_monotonic_ms() - started_ms));
    printf("\"errors\":{");
    printf("\"permission\":%u,", errors.permission);
    printf("\"not_found\":%u,", errors.not_found);
    printf("\"invalid\":%u,", errors.invalid);
    printf("\"unsupported\":%u,", errors.unsupported);
    printf("\"other\":%u}", errors.other);
    printf("}\n");
    return 0;
}
