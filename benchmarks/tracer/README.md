# Tracers benchmark

This directory consists of 2 main elements: file access simulation tool + tracing tools to record file access.

## Service Load Simulator: Loder
Loder is a benchmarking tool to apply file access and execution tasks at scale. Please refer to [loder/README.md](./loder/README.md) for more information.

## Tracer Tools

There are so many options to trace file access by a process. Here i collect some tools to benchmark them and compare them against each other:

### fanotify-cmd
[fanotify-cmd](./fanotify-cmd/) is a command line interface for [fanotify API](https://man7.org/linux/man-pages/man7/fanotify.7.html), which is written by myself. Then, I discovered `fatrace`, which uses the fanotify API as a backend and could not continue to develop due to implementation complexity. [Docker-slim](https://github.com/docker-slim/docker-slim/blob/master/pkg/app/sensor/monitors/fanotify/monitor.go) uses this tool to track app dependecies.
```bash
$ sudo fanotify-cmd/fanotify-cmd loder/loder --tasks loder/tasks.yml
```

### fatrace (uses fanotify internally)
`fatrace` is a command line tool which uses fanotify system call to track files used by certain processes. This program is written in C and seems to be active lately.
```bash
$ sudo fatrace --command loder &; pid=$!; sleep 1; ./loder/loder --tasks loder/tasks.yml; sudo kill $pid;
```

### strace
`strace` is a diagnostic, debugging and instructional userspace utility for Linux. It uses a system called tampering. [Hermit](https://github.com/SoftwareForHumans/hermit/blob/master/src/modules/tracer.ts) and [Cimplifier](../../related-works/cimplifier/code/straceparser.py) use this tool to find process dependencies. The biggest advantage of this method is it doesn't need a root privilage.
```bash
$ strace -s 200 -f -t -e trace=file ./loder/loder --tasks loder/tasks.yml 2>&1  | grep -P "\d+$" | cut -d "\"" -f 2
```
_TODO_: check theese options `trace=open,openat,close,read,getdents,write,connect,accept`

### ebpf: bpftrace
[`bpftrace`](https://github.com/iovisor/bpftrace) is a high-level tracing language for Linux enhanced Berkeley Packet Filter (eBPF). `bpftrace` uses LLVM as a backend to compile scripts to BPF-bytecode and makes use of BCC for interacting with the Linux BPF system, as well as existing Linux tracing capabilities.
```bash
$ sudo ./bpftrace/opensnoop.bt loder &; pid=$!; sleep 1; ./loder/loder --tasks loder/tasks.yml; sudo kill $pid;
```
