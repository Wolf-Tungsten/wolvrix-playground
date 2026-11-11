"""Run one workload in an independent, memory-capped user systemd service."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid


SCHEMA = "wolvrix.resource-capped.v1"
PROPERTIES = (
    "Id", "LoadState", "ActiveState", "SubState", "Result", "ExecMainCode",
    "ExecMainStatus", "ControlGroup", "MemoryCurrent", "MemoryPeak",
    "MemoryMax", "MemorySwapMax", "OOMPolicy", "KillMode",
    "RuntimeMaxUSec", "RuntimeRandomizedExtraUSec", "KillSignal", "SendSIGKILL",
)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def unified_cgroup() -> str:
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        if line.startswith("0::/"):
            return line[3:]
    raise RuntimeError("cgroup v2 is required")


def read_cgroup() -> dict:
    group = unified_cgroup()
    directory = Path("/sys/fs/cgroup") / group.lstrip("/")
    data = {"path": group}
    for name in ("memory.current", "memory.peak", "memory.max", "memory.swap.max",
                 "memory.swap.current", "memory.oom.group"):
        value = (directory / name).read_text().strip()
        data[name] = int(value) if value.isdigit() else value
    for name in ("memory.events", "memory.events.local", "memory.swap.events"):
        data[name] = {key: int(value) for key, value in
                      (line.split() for line in (directory / name).read_text().splitlines())}
    return data


def valid_enforcement(data: dict, limit: int, parent: str) -> bool:
    group = data.get("path", "")
    return (bool(group) and group != parent and not group.startswith(parent.rstrip("/") + "/")
            and data.get("memory.max") == limit
            and data.get("memory.swap.max") == 0
            and data.get("memory.oom.group") == 1)


def collect(path: Path, limit: int, parent: str, verify: bool, unit: str | None = None) -> int:
    data = {"schema": SCHEMA, "time": time.time(), "unit": unit}
    try:
        data["cgroup"] = read_cgroup()
        data["enforcement_verified"] = (valid_enforcement(data["cgroup"], limit, parent)
            and (unit is None or Path(data["cgroup"]["path"]).name == unit))
        if not data["enforcement_verified"]:
            data["error"] = "separate cgroup, memory.max, swap.max or oom.group did not match"
    except (OSError, RuntimeError, ValueError) as error:
        data["enforcement_verified"] = False
        data["error"] = str(error)
    if not verify:
        # systemd supplies these to ExecStopPost even when the main group was OOM-killed.
        data["service_result"] = os.environ.get("SERVICE_RESULT")
        data["exit_code"] = os.environ.get("EXIT_CODE")
        data["exit_status"] = os.environ.get("EXIT_STATUS")
    write_json(path, data)
    return 0 if not verify or data["enforcement_verified"] else 125


def systemd_word(value: str) -> str:
    # Exec*= uses systemd syntax, not shell syntax. ':' disables $ expansion;
    # literal percent specifiers and quoted backslashes still need escaping.
    if any(character in value for character in ("\x00", "\n", "\r")):
        raise ValueError("newline/NUL in systemd executable argument")
    return '"' + value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'


def exec_property(arguments: list[str]) -> str:
    return ":" + " ".join(systemd_word(argument) for argument in arguments)


def service_environment(environment: dict[str, str]) -> dict[str, str]:
    result = dict(environment)
    # A service cannot inherit the caller's jobserver descriptors. Keep Make
    # overrides and other flags; the recursive entry explicitly selects -j1.
    for name in ("MAKEFLAGS", "MFLAGS"):
        if name in result:
            result[name] = re.sub(r"(?:^|\s)--jobserver-(?:auth|fds)=\S+", "", result[name]).strip()
    return result


def make_command(command: list[str], unit: str, limit: int, output: Path,
                 parent: str, environment: dict[str, str],
                 runtime_max_seconds: int | None = None) -> list[str]:
    script = str(Path(__file__).resolve())
    common = [sys.executable, script, "--memory-max-bytes", str(limit),
              "--parent-cgroup", parent, "--unit-id", unit]
    arguments = [
        "systemd-run", "--user", "--no-ask-password", "--wait", "--pipe",
        "--quiet", "--service-type=exec", "--expand-environment=no",
        "--unit=" + unit, "--slice=app.slice", "--working-directory=" + str(Path.cwd()),
        "--property=MemoryAccounting=yes", "--property=MemoryMax=" + str(limit),
        "--property=MemorySwapMax=0", "--property=OOMPolicy=kill",
        "--property=KillMode=control-group", "--property=TimeoutStopSec=5s",
        "--property=ExecStartPre=" + exec_property(common + ["--verify-cgroup", str(output) + ".start.json"]),
        "--property=ExecStopPost=" + exec_property(common + ["--collect-cgroup", str(output) + ".stop.json"]),
    ]
    if runtime_max_seconds is not None:
        # A service deadline reaches nested process groups as well. Keep the
        # recorder outside the service and collect evidence in ExecStopPost.
        arguments.extend(("--property=RuntimeMaxSec=" + str(runtime_max_seconds) + "s",
                          "--property=RuntimeRandomizedExtraSec=0",
                          "--property=KillSignal=SIGKILL", "--property=SendSIGKILL=yes"))
    # NAME without '=value' tells systemd-run to copy its own environment.
    # Values (which may contain secrets) never enter the command line or report.
    arguments.extend("--setenv=" + name for name in sorted(environment)
                     if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))
    return arguments + ["--", *command]


def control(arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", "--no-pager", *arguments],
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=15, check=False)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def run(command: list[str], limit: int, output: Path,
        runtime_max_seconds: int | None = None) -> int:
    output = output.resolve()
    unit = "wolvrix-capped-" + uuid.uuid4().hex + ".service"
    report = {"schema": SCHEMA, "unit": unit, "memory_max_bytes": limit,
              "swap_max_bytes": 0, "started_at": time.time(),
              "status": "starting", "enforcement_verified": False}
    if runtime_max_seconds is not None:
        report["runtime_max_seconds"] = runtime_max_seconds
    write_json(output, report)
    started = time.monotonic()
    launched = False
    interrupted = False
    previous_handlers = {}
    status = 125
    try:
        # Retries use a new UUID unit. Never combine its result with evidence
        # left by an earlier service that used the same report path.
        for phase in ("start", "stop"):
            Path(str(output) + "." + phase + ".json").unlink(missing_ok=True)
        parent = unified_cgroup()
        availability = control(["show", "--property=Version"])
        if availability.returncode:
            raise RuntimeError("user systemd manager unavailable: " + availability.stderr.strip())
        environment = service_environment(dict(os.environ))
        arguments = make_command(command, unit, limit, output, parent, environment, runtime_max_seconds)

        def interrupt(signum, frame):
            raise KeyboardInterrupt

        for signum in (signal.SIGTERM, signal.SIGHUP):
            previous_handlers[signum] = signal.signal(signum, interrupt)
        launched = True
        print(f"[resource-cap] unit={unit} memory_max_bytes={limit} swap_max_bytes=0", flush=True)
        status = subprocess.run(arguments, env=environment, check=False).returncode
        report["systemd_run_returncode"] = status
    except KeyboardInterrupt:
        interrupted = True
        status = 130
        report["error"] = "invoking process interrupted"
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        status = 125
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        if launched:
            try:
                if interrupted:
                    control(["stop", unit])
                shown = control(["show", unit, *["--property=" + name for name in PROPERTIES]])
                report["systemd_properties"] = dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
                report["systemd_show_returncode"] = shown.returncode
                start = read_json(Path(str(output) + ".start.json"))
                stop = read_json(Path(str(output) + ".stop.json"))
                report["cgroup_start"] = start
                report["cgroup_stop"] = stop
                report["enforcement_verified"] = bool(
                    start and stop and start.get("enforcement_verified") and stop.get("enforcement_verified")
                    and start.get("unit") == unit and stop.get("unit") == unit
                    and start.get("cgroup", {}).get("path") == stop.get("cgroup", {}).get("path"))
                if not report["enforcement_verified"]:
                    report.setdefault("error", "memory enforcement evidence incomplete; refusing success")
                    if status == 0:
                        status = 125
                if stop:
                    report["memory_peak_bytes"] = stop.get("cgroup", {}).get("memory.peak")
                    report["result"] = stop.get("service_result")
                    report["exec_main_status"] = stop.get("exit_status")
                    report["exec_main_code"] = stop.get("exit_code")
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                report["evidence_error"] = str(error)
                if status == 0:
                    status = 125
            finally:
                # Only this invocation's UUID unit is touched, never the parent scope.
                try:
                    control(["stop", unit])
                    control(["reset-failed", unit])
                except (OSError, subprocess.SubprocessError):
                    pass
        report["ended_at"] = time.time()
        report["elapsed_s"] = time.monotonic() - started
        report["returncode"] = status
        report["status"] = "success" if status == 0 else "failed"
        write_json(output, report)
    return status if status >= 0 else 128 - status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-max-bytes", type=int, required=True)
    parser.add_argument("--runtime-max-seconds", type=int,
                        help="optional service-wide runtime deadline with immediate group SIGKILL")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--parent-cgroup", help=argparse.SUPPRESS)
    parser.add_argument("--unit-id", help=argparse.SUPPRESS)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--verify-cgroup", type=Path, help=argparse.SUPPRESS)
    modes.add_argument("--collect-cgroup", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.memory_max_bytes <= 0:
        parser.error("--memory-max-bytes must be positive")
    if args.runtime_max_seconds is not None and args.runtime_max_seconds <= 0:
        parser.error("--runtime-max-seconds must be positive")
    if args.verify_cgroup or args.collect_cgroup:
        if not args.parent_cgroup:
            parser.error("collector requires --parent-cgroup")
        return collect(args.verify_cgroup or args.collect_cgroup, args.memory_max_bytes,
                       args.parent_cgroup, args.verify_cgroup is not None, args.unit_id)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not args.output or not command:
        parser.error("--output and a command after -- are required")
    return run(command, args.memory_max_bytes, args.output, args.runtime_max_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
