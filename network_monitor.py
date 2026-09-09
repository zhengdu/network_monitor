#!/usr/bin/env python3

import argparse
import datetime as dt
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_DURATION_HOURS = 2
DEFAULT_INTERVAL_SECONDS = 5
DEFAULT_EXTERNAL_TARGET = "8.8.8.8"


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Continuously monitor network connectivity by pinging the router gateway "
            "and the external target, then write results to a timestamped TXT log file."
        )
    )
    parser.add_argument(
        "--duration-hours",
        type=float,
        default=DEFAULT_DURATION_HOURS,
        help=f"How long to run the monitor (default: {DEFAULT_DURATION_HOURS} hours)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Seconds between each ping cycle (default: {DEFAULT_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--external-target",
        default=DEFAULT_EXTERNAL_TARGET,
        help=f"External IP/domain to test (default: {DEFAULT_EXTERNAL_TARGET})",
    )
    parser.add_argument(
        "--log-dir",
        default=".",
        help="Directory where the log file should be created (default: current directory)",
    )
    parser.add_argument(
        "--gateway",
        default=None,
        help="Optional gateway IP override. If omitted, the program auto-detects it.",
    )
    return parser.parse_args()


def now_str():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_duration(total_seconds):
    total_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def detect_event_type(gateway_ok, internet_ok):
    if gateway_ok and internet_ok:
        return "NORMAL"
    if gateway_ok:
        return "INTERNET_ONLY"
    if internet_ok:
        return "GATEWAY_ONLY"
    return "BOTH_FAIL"


def detect_gateway():
    try:
        proc = subprocess.run(
            ["route", "-n", "get", "default"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None, "Could not detect gateway automatically (route -n get default unavailable or timed out)."

    if proc.returncode != 0:
        return None, proc.stderr.strip() or proc.stdout.strip() or "route command failed."

    gateway_match = re.search(r"gateway:\s*([0-9.]+)", proc.stdout)
    if gateway_match:
        return gateway_match.group(1), None

    return None, "No default gateway found in route output."


def extract_rtt(output):
    match = re.search(r"time=([0-9.]+)\s*ms", output, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def ping_once(target):
    try:
        completed = subprocess.run(
            ["ping", "-c", "1", target],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "rtt": None,
            "error": "ping command timed out",
            "raw": "",
        }

    output = (completed.stdout or "") + (completed.stderr or "")
    output = output.strip()
    ok = completed.returncode == 0
    rtt = extract_rtt(output)
    reason = "ok" if ok else (output or "ping failed")

    return {
        "ok": ok,
        "rtt": rtt,
        "error": None if ok else reason,
        "raw": output,
    }


def log_line(handle, line):
    handle.write(line + "\n")
    handle.flush()


def summarize_log(log_path, summary_path):
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        error_lines = [f"[SUMMARY] Failed to read log file {log_path}: {exc}"]
        summary_path.write_text("\n".join(error_lines) + "\n", encoding="utf-8")
        print(error_lines[0])
        return

    events = []
    current_event = None

    for line in lines:
        start_match = re.search(
            r"^\[(.*?)\] EVENT_START type=([A-Z_]+).*gateway=(OK|FAIL|FINAL) internet=(OK|FAIL|FINAL)$",
            line,
        )
        if start_match:
            start_time = start_match.group(1)
            current_event = {
                "start": start_time,
                "type": start_match.group(2),
                "gateway_start": start_match.group(3),
                "internet_start": start_match.group(4),
            }
            events.append(current_event)
            continue

        end_match = re.search(
            r"^\[(.*?)\] EVENT_END type=([A-Z_]+) duration=([^ ]+) gateway=(OK|FAIL|FINAL) internet=(OK|FAIL|FINAL)$",
            line,
        )
        if end_match:
            end_time = end_match.group(1)
            event_type = end_match.group(2)
            duration = end_match.group(3)
            gateway_end = end_match.group(4)
            internet_end = end_match.group(5)

            if current_event is None:
                current_event = {
                    "start": end_time,
                    "type": event_type,
                    "gateway_start": gateway_end,
                    "internet_start": internet_end,
                }
                events.append(current_event)

            current_event["end"] = end_time
            current_event["duration"] = duration
            current_event["gateway_end"] = gateway_end
            current_event["internet_end"] = internet_end
            current_event = None

    summary_lines = [f"[SUMMARY] Log file: {log_path}", f"[SUMMARY] Total outage events detected: {len(events)}"]

    if not events:
        summary_lines.append("[SUMMARY] No outage events were detected in this run.")
    else:
        for idx, event in enumerate(events, start=1):
            start = event.get("start", "unknown")
            end = event.get("end", start)
            duration = event.get("duration", "0s")
            summary_lines.append(
                f"[SUMMARY] Event {idx}: type={event['type']} | "
                f"start={start} | end={end} | duration={duration} | "
                f"gateway={event.get('gateway_start', 'N/A')}->{event.get('gateway_end', event.get('gateway_start', 'N/A'))} | "
                f"internet={event.get('internet_start', 'N/A')}->{event.get('internet_end', event.get('internet_start', 'N/A'))}"
            )

        breakdown = {}
        for event in events:
            event_type = event["type"]
            breakdown[event_type] = breakdown.get(event_type, 0) + 1

        summary_lines.append("[SUMMARY] Breakdown by failure type:")
        for event_type, count in breakdown.items():
            summary_lines.append(f"  - {event_type}: {count} event(s)")

    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print(f"\n[SUMMARY] Summary saved to {summary_path}")
    for line in summary_lines:
        print(line)


def main():
    args = parse_args()
    duration_seconds = max(args.duration_hours * 3600, 1)
    interval_seconds = max(args.interval_seconds, 1)

    log_dir = Path(args.log_dir).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"network_monitor_{timestamp}.txt"
    summary_path = log_dir / f"network_monitor_summary_{timestamp}.txt"

    if args.gateway:
        gateway = args.gateway
        gateway_error = None
    else:
        gateway, gateway_error = detect_gateway()

    if gateway_error:
        print(f"[WARN] Could not auto-detect gateway: {gateway_error}")
        print("You can rerun with --gateway <ip> to specify a manual gateway.")

    if not gateway:
        print("[ERROR] No gateway available. Exiting.")
        sys.exit(1)

    external_target = args.external_target
    start_time = dt.datetime.now()
    end_time = start_time + dt.timedelta(seconds=duration_seconds)
    total_samples = 0
    gateway_failures = 0
    internet_failures = 0
    current_event = None
    outage_events = []

    print(f"[{now_str()}] Starting network monitor")
    print(f"[{now_str()}] Duration: {args.duration_hours} hours")
    print(f"[{now_str()}] Interval: {interval_seconds} seconds")
    print(f"[{now_str()}] Gateway: {gateway}")
    print(f"[{now_str()}] External target: {external_target}")
    print(f"[{now_str()}] Log file: {log_path}")

    with log_path.open("a", encoding="utf-8") as log_file:
        log_line(
            log_file,
            f"[{start_time.strftime('%Y-%m-%d %H:%M:%S')}] START duration_hours={args.duration_hours} interval_seconds={interval_seconds} gateway={gateway} external_target={external_target}",
        )

        while dt.datetime.now() < end_time:
            sample_time = dt.datetime.now()
            gateway_result = ping_once(gateway)
            internet_result = ping_once(external_target)
            total_samples += 1

            if not gateway_result["ok"]:
                gateway_failures += 1
            if not internet_result["ok"]:
                internet_failures += 1

            gateway_status = "OK" if gateway_result["ok"] else "FAIL"
            internet_status = "OK" if internet_result["ok"] else "FAIL"

            gateway_rtt = gateway_result["rtt"]
            if gateway_rtt is None:
                gateway_rtt_str = "N/A"
            else:
                gateway_rtt_str = f"{gateway_rtt:.1f}ms"

            internet_rtt = internet_result["rtt"]
            if internet_rtt is None:
                internet_rtt_str = "N/A"
            else:
                internet_rtt_str = f"{internet_rtt:.1f}ms"

            line = (
                f"[{sample_time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"gateway={gateway_status} gateway_rtt={gateway_rtt_str} "
                f"internet={internet_status} internet_rtt={internet_rtt_str} "
                f"gateway_error={gateway_result['error'] or 'none'} "
                f"internet_error={internet_result['error'] or 'none'}"
            )
            log_line(log_file, line)
            print(line)

            outage_active = not gateway_result["ok"] or not internet_result["ok"]
            if outage_active and current_event is None:
                current_event = {
                    "start": sample_time,
                    "type": detect_event_type(gateway_result["ok"], internet_result["ok"]),
                }
                log_line(
                    log_file,
                    f"[{sample_time.strftime('%Y-%m-%d %H:%M:%S')}] EVENT_START type={current_event['type']} gateway={gateway_status} internet={internet_status}",
                )
            elif not outage_active and current_event is not None:
                end_time_for_event = sample_time
                duration_seconds = (end_time_for_event - current_event["start"]).total_seconds()
                current_event["end"] = end_time_for_event
                current_event["duration_seconds"] = duration_seconds
                outage_events.append(current_event)
                log_line(
                    log_file,
                    f"[{end_time_for_event.strftime('%Y-%m-%d %H:%M:%S')}] EVENT_END type={current_event['type']} duration={format_duration(duration_seconds)} gateway={gateway_status} internet={internet_status}",
                )
                current_event = None

            if dt.datetime.now() + dt.timedelta(seconds=interval_seconds) < end_time:
                time.sleep(interval_seconds)
            else:
                break

        finish_time = dt.datetime.now()

        if current_event is not None:
            current_event["end"] = finish_time
            current_event["duration_seconds"] = (finish_time - current_event["start"]).total_seconds()
            outage_events.append(current_event)
            log_line(
                log_file,
                f"[{finish_time.strftime('%Y-%m-%d %H:%M:%S')}] EVENT_END type={current_event['type']} duration={format_duration(current_event['duration_seconds'])} gateway=FINAL internet=FINAL",
            )

        total_outage_seconds = sum(event["duration_seconds"] for event in outage_events)
        summary_line = (
            f"[{finish_time.strftime('%Y-%m-%d %H:%M:%S')}] END "
            f"samples={total_samples} gateway_failures={gateway_failures} internet_failures={internet_failures} total_events={len(outage_events)} total_outage_time={format_duration(total_outage_seconds)}"
        )
        log_line(log_file, summary_line)
        print(summary_line)

        if outage_events:
            print(f"[{finish_time.strftime('%Y-%m-%d %H:%M:%S')}] SUMMARY")
            for index, event in enumerate(outage_events, start=1):
                summary_event_line = (
                    f"[{finish_time.strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"EVENT_SUMMARY index={index} type={event['type']} "
                    f"start={event['start'].strftime('%Y-%m-%d %H:%M:%S')} "
                    f"end={event['end'].strftime('%Y-%m-%d %H:%M:%S')} "
                    f"duration={format_duration(event['duration_seconds'])}"
                )
                log_line(log_file, summary_event_line)
                print(summary_event_line)

    summarize_log(log_path, summary_path)
    print(f"[DONE] Log saved to {log_path}")
    print(f"[DONE] Summary saved to {summary_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Monitoring stopped by user.")
        sys.exit(0)
