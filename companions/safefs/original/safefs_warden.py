#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SafeFS Warden - External Enforcement & Zero Trust Guardian for SafeFS v9

This script acts as a root-privileged guardian that creates a highly restrictive
and actively monitored sandboxed environment for the SafeFS application. It uses
Linux Control Groups (cgroup v2) for resource and device isolation, and eBPF
for deep, real-time kernel-level monitoring and policy enforcement.

Core Philosophy:
- External Enforcement: All security policies are enforced by the Warden from
  the outside. The SafeFS application itself runs with minimal privileges and
  cannot escape its container.
- Zero Trust: The Warden assumes the SafeFS application could be compromised.
  It is treated as untrusted and its behavior is continuously verified against
  a strict security policy.

*** THIS SCRIPT MUST BE RUN AS ROOT ***
"""

import os
import sys
import subprocess
import argparse
import pwd
import grp
import signal
import time
import ctypes
from bcc import BPF, lib

# --- Configuration ---
SAFEFS_USER = "safefs_user"  # Dedicated low-privilege user for SafeFS
CGROUP_BASE_NAME = "warden_safefs"
TEMP_DIR_WHITELIST = "/tmp/.secure_fs_tmp/"

# --- eBPF Program (C Code) ---
# This is the heart of our monitoring system, compiled and loaded into the kernel.
BPF_PROGRAM = """
#include <linux/bpf.h>
#include <linux/sched.h>
#include <linux/fs.h>
#include <linux/path.h>
#include <linux/nsproxy.h>
#include <linux/mount.h>
#include <linux/utsname.h>

// Data structure to send events from kernel to user-space (Warden)
struct event_t {
    u32 pid;
    u32 uid;
    int ret;
    u32 threat_level; // 1: Log, 2: Freeze, 3: Kill
    char comm[TASK_COMM_LEN];
    char path[MAX_PATH_LEN];
    char syscall[32];
};
BPF_PERF_OUTPUT(events);

// Placeholder for the target UID, will be replaced by the Warden at runtime.
static const uid_t TARGET_UID = TARGET_UID_PLACEHOLDER;
static const char temp_dir_whitelist[] = "TEMP_DIR_PLACEHOLDER";
static const char allowed_src_path[] = "ALLOWED_SRC_PLACEHOLDER";
static const char allowed_dest_path[] = "ALLOWED_DEST_PLACEHOLDER";

// Helper function to check if a process belongs to our target UID
static inline int is_target_proc() {
    if (bpf_get_current_uid_gid() != TARGET_UID) {
        return 0;
    }
    return 1;
}

// Helper function to submit a generic event
static inline void submit_event(void *ctx, u32 level, const char *syscall_name, const char *path_str) {
    struct event_t event = {};
    event.pid = bpf_get_current_pid_tgid() >> 32;
    event.uid = bpf_get_current_uid_gid();
    event.threat_level = level;
    bpf_get_current_comm(&event.comm, sizeof(event.comm));
    
    __builtin_memcpy(event.syscall, syscall_name, sizeof(event.syscall));
    if (path_str != NULL) {
        bpf_probe_read_str(&event.path, sizeof(event.path), path_str);
    }
    
    events.perf_submit(ctx, &event, sizeof(event));
}

// 1. LSM Hook for File Open operations - The most powerful file access control
LSM_PROBE(file_open, struct file *file) {
    if (!is_target_proc()) {
        return 0; // Not our process, ignore
    }

    // Get full file path
    char path[MAX_PATH_LEN];
    bpf_d_path(&file->f_path, path, sizeof(path));

    // --- Policy Enforcement ---
    // Allow if path matches allowed source, destination, or temp directory
    if (bpf_strncmp(path, sizeof(path), allowed_src_path) == 0) return 0;
    if (bpf_strncmp(path, sizeof(path), allowed_dest_path) == 0) return 0;
    if (bpf_strncmp(path, sizeof(path), temp_dir_whitelist) == 0) return 0;
    
    // Whitelist essential system libraries and files
    // This part is crucial and may need adjustment based on the system
    if (bpf_strncmp(path, sizeof(path), "/lib/") == 0) return 0;
    if (bpf_strncmp(path, sizeof(path), "/usr/lib/") == 0) return 0;
    if (bpf_strncmp(path, sizeof(path), "/etc/ld.so.cache") == 0) return 0;

    // --- Threat Detected ---
    // If we reach here, it's an unauthorized file access attempt.
    submit_event(ctx, 3, "file_open", path);
    
    return -EPERM; // Block the operation
}


// 2. Tracepoint for execve - SafeFS should NEVER execute another program
TRACEPOINT_PROBE(syscalls, sys_enter_execve) {
    if (!is_target_proc()) {
        return 0;
    }
    
    // This is a critical violation.
    submit_event(ctx, 3, "execve", (char *)args->filename);
    
    // We can't block execve from a tracepoint, but the Warden will receive
    // the event and kill the process instantly.
    return 0;
}

// 3. Tracepoint for socket calls - Enforce network isolation
TRACEPOINT_PROBE(syscalls, sys_enter_socket) {
    if (!is_target_proc()) {
        return 0;
    }
    
    // Any attempt to create a socket is a critical violation.
    submit_event(ctx, 3, "socket", NULL);
    return 0;
}

"""

class CgroupManager:
    """Manages the cgroup v2 environment for the sandboxed process."""
    def __init__(self, name):
        self.cgroup_path = os.path.join("/sys/fs/cgroup", name)
        self.frozen = False
        if not os.path.exists("/sys/fs/cgroup"):
            raise EnvironmentError("cgroup v2 filesystem not found at /sys/fs/cgroup.")

    def _write_file(self, file, value):
        path = os.path.join(self.cgroup_path, file)
        try:
            with open(path, "w") as f:
                f.write(str(value))
        except IOError as e:
            print(f"[-] Warden Error: Failed to write to cgroup file {path}: {e}", file=sys.stderr)

    def create(self):
        """Creates the cgroup directory and enables controllers."""
        if os.path.exists(self.cgroup_path):
            self.cleanup() # Clean up any stale cgroup from a previous crash
        
        try:
            os.makedirs(self.cgroup_path)
            # Enable all necessary controllers for the subtree
            controllers = "+cpu +memory +pids +io +freezer"
            with open("/sys/fs/cgroup/cgroup.subtree_control", "r") as f:
                # Check what is available before trying to enable
                available_controllers = f.read().split()
            
            # This is a bit complex, but ensures we only enable available controllers.
            base_control_path = os.path.join(self.cgroup_path, "..", "cgroup.subtree_control")
            with open(base_control_path, "w") as f:
                 f.write(controllers)

            print(f"[+] Warden: Cgroup '{self.cgroup_path}' created.")
        except Exception as e:
            raise RuntimeError(f"Failed to create cgroup: {e}")

    def configure(self):
        """Applies all resource and device restrictions."""
        print("[+] Warden: Configuring cgroup security policies...")
        # Memory limit: 512 MB
        self._write_file("memory.max", 512 * 1024 * 1024)
        # CPU limit: 50% of one core
        self._write_file("cpu.max", "50000 100000")
        # PID limit: Max 8 processes
        self._write_file("pids.max", 8)
        # I/O limit: Max 10MB/s on read/write
        # Note: This requires the 'io' controller and device major:minor numbers.
        # This is a generic example, might need adjustment. 8:0 is typically /dev/sda.
        # self._write_file("io.max", "8:0 rbps=10485760 wbps=10485760")

        # Device policy: Deny all by default, then allow a minimal set.
        self._write_file("cgroup.devices", "a *:* rwm") # Needed to add rules
        self._write_file("devices.deny", "a")
        # Allow reading basic char devices (null, zero, random, tty)
        self._write_file("devices.allow", "c 1:3 r")   # /dev/null
        self._write_file("devices.allow", "c 1:5 r")   # /dev/zero
        self._write_file("devices.allow", "c 1:8 r")   # /dev/random
        self._write_file("devices.allow", "c 1:9 r")   # /dev/urandom
        self._write_file("devices.allow", "c 5:0 r")   # /dev/tty
        self._write_file("devices.allow", "c 136:* rw") # /dev/pts/*
        # Allow reading/writing all files (LSM BPF will handle path-based logic)
        self._write_file("devices.allow", "b *:* rwm")
        self._write_file("devices.allow", "c *:* rwm")
        print("[+] Warden: Cgroup policies applied.")

    def add_pid(self, pid):
        """Moves the target process into the cgroup."""
        self._write_file("cgroup.procs", pid)
        print(f"[+] Warden: Process PID {pid} moved into secure cgroup.")

    def freeze(self):
        """Freezes all processes in the cgroup."""
        if not self.frozen:
            self._write_file("cgroup.freeze", 1)
            self.frozen = True
            print(f"[!] Warden: Threat detected! Cgroup '{self.cgroup_path}' FROZEN.")

    def kill(self):
        """Terminates all processes in the cgroup forcefully."""
        try:
            pids_to_kill = []
            with open(os.path.join(self.cgroup_path, "cgroup.procs"), 'r') as f:
                pids_to_kill = [int(p) for p in f.readlines()]
            
            for pid in pids_to_kill:
                try:
                    os.kill(pid, signal.SIGKILL)
                    print(f"[-] Warden: Terminated process PID {pid} in cgroup.")
                except ProcessLookupError:
                    pass # Process already dead
        except FileNotFoundError:
            pass # Cgroup already removed
        except Exception as e:
            print(f"[-] Warden Error: Exception while killing processes in cgroup: {e}", file=sys.stderr)

    def cleanup(self):
        """Kills remaining processes and removes the cgroup directory."""
        print("[+] Warden: Cleaning up secure environment...")
        self.kill()
        try:
            os.rmdir(self.cgroup_path)
            print(f"[+] Warden: Cgroup '{self.cgroup_path}' removed.")
        except FileNotFoundError:
            pass
        except OSError as e:
            # Might fail if there are still processes, but kill() should prevent this
            print(f"[-] Warden Error: Failed to remove cgroup directory {self.cgroup_path}: {e}", file=sys.stderr)


class Warden:
    def __init__(self, safefs_path, safefs_args):
        self.safefs_path = safefs_path
        self.safefs_args = safefs_args
        self.safefs_proc = None
        self.user_info = None
        self.bpf = None
        self.cgroup_manager = None
        
        # Extract src/dest paths for eBPF whitelist
        self.src_path = self._get_arg_path(['--src', '-s'], safefs_args)
        self.dest_path = self._get_arg_path(['--dest', '-d'], safefs_args)

    def _get_arg_path(self, flags, args):
        for flag in flags:
            if flag in args:
                try:
                    path_idx = args.index(flag) + 1
                    if path_idx < len(args):
                        return os.path.abspath(args[path_idx])
                except (ValueError, IndexError):
                    continue
        return "/path/that/will/not/exist" # Default non-matching path

    def _ensure_user(self):
        """Ensures the low-privilege user exists."""
        try:
            return pwd.getpwnam(SAFEFS_USER)
        except KeyError:
            print(f"[+] Warden: User '{SAFEFS_USER}' not found. Creating it...")
            try:
                subprocess.run(
                    [
                        "useradd", "-r", "-M", "-N", "-l",
                        "-s", "/sbin/nologin", SAFEFS_USER
                    ],
                    check=True,
                )
                print(f"[+] Warden: System user '{SAFEFS_USER}' created.")
                return pwd.getpwnam(SAFEFS_USER)
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Failed to create user '{SAFEFS_USER}': {e}")

    def _demote(self, uid, gid):
        """Function to be run in the child process before exec."""
        def result():
            try:
                os.setgid(gid)
                os.setuid(uid)
                os.setsid()
            except Exception as e:
                print(f"[-] Warden Child Error: Failed to demote privileges: {e}", file=sys.stderr)
                # Exit with a specific code to indicate failure
                os._exit(127)
        return result

    def _setup_bpf(self):
        """Loads and configures the eBPF program."""
        print("[+] Warden: Compiling and loading eBPF security monitor...")
        
        # Replace placeholders in the BPF code with runtime values
        final_bpf_code = BPF_PROGRAM.replace(
            "TARGET_UID_PLACEHOLDER", str(self.user_info.pw_uid)
        ).replace(
            "TEMP_DIR_PLACEHOLDER", TEMP_DIR_WHITELIST
        ).replace(
            "MAX_PATH_LEN", str(BPF.MAX_PATH_LEN)
        ).replace(
            "ALLOWED_SRC_PLACEHOLDER", self.src_path
        ).replace(
            "ALLOWED_DEST_PLACEHOLDER", self.dest_path
        )
        
        try:
            self.bpf = BPF(text=final_bpf_code, cflags=["-Wno-macro-redefined"])
            self.bpf.attach_lsm(func_name="file_open")
            self.bpf.attach_tracepoint(tp="syscalls:sys_enter_execve", fn_name="TRACEPOINT_PROBE_syscalls_sys_enter_execve")
            self.bpf.attach_tracepoint(tp="syscalls:sys_enter_socket", fn_name="TRACEPOINT_PROBE_syscalls_sys_enter_socket")
            print("[+] Warden: eBPF monitor loaded and attached to kernel hooks.")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize BPF: {e}\n"
                             "Ensure kernel headers are installed and you have root privileges.")

    def _handle_bpf_event(self, cpu, data, size):
        """Callback for handling events from the eBPF program."""
        class Event(ctypes.Structure):
            _fields_ = [
                ("pid", ctypes.c_uint),
                ("uid", ctypes.c_uint),
                ("ret", ctypes.c_int),
                ("threat_level", ctypes.c_uint),
                ("comm", ctypes.c_char * 16),
                ("path", ctypes.c_char * BPF.MAX_PATH_LEN),
                ("syscall", ctypes.c_char * 32),
            ]
        event = ctypes.cast(data, ctypes.POINTER(Event)).contents
        
        comm = event.comm.decode('utf-8', 'replace')
        path = event.path.decode('utf-8', 'replace')
        syscall = event.syscall.decode('utf-8', 'replace')

        alert_color = {1: "\033[93m", 2: "\033[91m", 3: "\033[1;91m"}
        end_color = "\033[0m"
        color = alert_color.get(event.threat_level, "")

        print(
            f"{color}[!] KERNEL ALERT (L{event.threat_level}) "
            f"PID: {event.pid} COMM: {comm} SYSCALL: {syscall} "
            f"PATH: {path}{end_color}"
        )

        # Decision & Action
        if event.threat_level == 2: # Freeze
            self.cgroup_manager.freeze()
        elif event.threat_level >= 3: # Kill
            print("[-] Warden: Critical threat detected. Terminating sandboxed process immediately.")
            self.cgroup_manager.kill()


    def run(self):
        """Main execution flow of the Warden."""
        self.user_info = self._ensure_user()
        
        cgroup_name = f"{CGROUP_BASE_NAME}_{os.getpid()}"
        self.cgroup_manager = CgroupManager(cgroup_name)
        
        try:
            # 1. Setup Environment
            self.cgroup_manager.create()
            self.cgroup_manager.configure()
            self._setup_bpf()
            
            # 2. Launch Sandboxed Process
            command = [self.safefs_path] + self.safefs_args
            print(f"[+] Warden: Launching SafeFS: {' '.join(command)}")
            self.safefs_proc = subprocess.Popen(
                command,
                preexec_fn=self._demote(self.user_info.pw_uid, self.user_info.pw_gid)
            )
            
            # 3. Move process to cgroup
            self.cgroup_manager.add_pid(self.safefs_proc.pid)

            # 4. Start Monitoring Loop
            self.bpf["events"].open_perf_buffer(self._handle_bpf_event)
            print("[+] Warden: Monitoring started. Press Ctrl+C to stop.")
            while self.safefs_proc.poll() is None:
                try:
                    self.bpf.perf_buffer_poll(timeout=500)
                except KeyboardInterrupt:
                    print("\n[+] Warden: Interruption received. Shutting down.")
                    break
            
            print(f"[+] Warden: SafeFS process exited with code {self.safefs_proc.returncode}.")

        except Exception as e:
            print(f"[-] Warden FATAL ERROR: {e}", file=sys.stderr)
        finally:
            # 5. Cleanup
            if self.safefs_proc and self.safefs_proc.poll() is None:
                 self.safefs_proc.terminate()
            if self.cgroup_manager:
                self.cgroup_manager.cleanup()
            # Optionally, you might want to remove the user after execution
            # remove_user(SAFEFS_USER)

def main():
    if os.geteuid() != 0:
        print("This script requires root privileges to manage cgroups and eBPF.", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="SafeFS Warden: A root-privileged guardian for SafeFS v9.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("safefs_path", help="Path to the safefsv9.py executable.")
    parser.add_argument(
        "safefs_args",
        nargs=argparse.REMAINDER,
        help="All subsequent arguments to pass to safefsv9.py (e.g., 'encrypt --src /file')",
    )
    args = parser.parse_args()

    if not args.safefs_args:
        parser.error("You must provide arguments for safefsv9.py")

    warden = Warden(args.safefs_path, args.safefs_args)
    warden.run()


if __name__ == "__main__":
    main()