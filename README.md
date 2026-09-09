# Network Monitor

这是一个用于持续监控网络连通性的 Python 脚本。它会在指定时间内周期性执行 `ping`，同时检查：

- 路由器网关（gateway）是否可达
- 外部目标（例如 8.8.8.8）是否可达

脚本会把每次检测结果写入时间戳命名的日志文件，并在运行结束后自动生成一份汇总摘要。

## 功能简介

- 自动检测默认网关（使用 `route -n get default`）
- 轮询 ping 网关和外部目标
- 记录每次检测的 RTT、成功/失败状态、错误原因
- 在出现网络中断时自动标记事件开始/结束
- 运行结束后生成 `network_monitor_summary_*.txt` 摘要文件

## 运行前提

该脚本依赖以下系统命令：

- `ping`
- `route`（用于自动检测网关）

适用于 macOS / 类 Unix 环境。原脚本里自动检测网关用的是 `route -n get default`，因此在 macOS 上最稳妥。

## 基本用法

在当前目录执行：

```bash
python3 network_monitor.py
```

默认行为：

- 运行时长：2 小时
- 检测间隔：5 秒
- 外部目标：8.8.8.8
- 日志目录：当前目录
- 网关：自动检测

## 可用参数

```bash
python3 network_monitor.py --help
```

支持的参数如下：

- `--duration-hours`  
  监控持续时长（小时），默认值为 `2`

- `--interval-seconds`  
  每轮检测的间隔秒数，默认值为 `5`

- `--external-target`  
  要测试的外部 IP / 域名，默认值为 `8.8.8.8`

- `--log-dir`  
  日志文件输出目录，默认值为当前目录

- `--gateway`  
  手动指定网关 IP；如果不提供，则自动检测默认网关

## 常见用法示例

### 1. 监控 2 小时，间隔 10 秒（默认值示例）

```bash
python3 network_monitor.py --duration-hours 2 --interval-seconds 10
```

### 2. 自定义运行时长

如果你不想跑默认的 2 小时，可以在运行时直接传入想要的小时数，例如：

```bash
python3 network_monitor.py --duration-hours 1
```

### 3. 测试某个外部目标

```bash
python3 network_monitor.py --external-target 1.1.1.1
```

### 4. 指定网关并写入到指定目录

```bash
python3 network_monitor.py --gateway 192.168.1.1 --log-dir ./logs
```

### 5. 只监控 30 分钟

```bash
python3 network_monitor.py --duration-hours 0.5
```

## 输出文件

脚本会在运行时生成两个文件：

### 1. 详细日志

例如：

```text
network_monitor_20260908_104939.txt
```

内容包括：

- 每次 ping 的网关状态
- 每次 ping 的外部目标状态
- RTT（响应时间）
- 失败原因
- 事件开始/结束标记
- 最终运行摘要

### 2. 汇总文件

例如：

```text
network_monitor_summary_20260908_104939.txt
```

汇总文件会分析日志并输出：

- 一共检测到了多少个故障事件
- 每个事件的开始时间、结束时间、持续时间
- 故障类别（例如 `INTERNET_ONLY`, `GATEWAY_ONLY`, `BOTH_FAIL`）
- 各类型事件的数量统计

## 日志中的事件说明

脚本会在网关或互联网出现异常时记录事件，事件类型包括：

- `NORMAL`：网关和外部目标都正常
- `INTERNET_ONLY`：网关正常，但外部目标失败
- `GATEWAY_ONLY`：外部目标正常，但网关失败
- `BOTH_FAIL`：网关和外部目标都失败

## 示例输出

运行时会在终端中实时输出类似内容：

```text
[2026-09-08 10:49:39] Starting network monitor
[2026-09-08 10:49:39] Duration: 2 hours
[2026-09-08 10:49:39] Interval: 5 seconds
[2026-09-08 10:49:39] Gateway: 192.168.4.1
[2026-09-08 10:49:39] External target: 8.8.8.8
[2026-09-08 10:49:39] Log file: ./network_monitor_20260908_104939.txt
[2026-09-08 10:53:42] gateway=OK gateway_rtt=6.9ms internet=FAIL internet_rtt=N/A gateway_error=none internet_error=ping command timed out
```

运行结束后，终端还会输出类似：

```text
[2026-09-08 10:49:39] END samples=... gateway_failures=... internet_failures=... total_events=... total_outage_time=...
```

## 停止运行

在终端中按：

```bash
Ctrl+C
```

脚本会捕获 `KeyboardInterrupt`，并输出：

```text
[INFO] Monitoring stopped by user.
```

## 注意事项

- 如果未提供 `--gateway`，脚本会尝试自动检测网关；如果检测失败，可以手动传入 `--gateway`。
- 若 `ping` 或 `route` 命令不可用，脚本可能无法正常运行。
- 该脚本会持续运行到指定时长结束，若希望更短的测试，可使用较小的 `--duration-hours`。
- `ping` 可能因为网络抖动而出现偶发失败；建议结合日志和汇总文件分析稳定性的趋势。

## 目录说明

在本项目中，已有一些示例日志文件：

- `network_monitor_*.txt`：原始监控日志
- `network_monitor_summary_*.txt`：汇总分析结果

这些文件可以用来确认脚本输出结构与使用方式。
