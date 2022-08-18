# Loder
is a command line tool to apply read/write/execute files as configured in tasks yaml file.

## Task yaml file structure

Containes an array of tasks with the following keys:

- kind: what kind of tasks should be executed.
  - read: read first 4 bytes of files
  - write: write 4 bytes in a file
  - execute-subproc: run another binary (execve syscalls)
  - execute-subthread: run a binary in a os thread
  - create-delete: create a file and then delete it
  - fork: fork a procces. use fork + clone + vfork syscalls
  - chmod: use fchmodat syscall. (*NOTE*: file should exist.)
- files: arrays of files paths which task action should apply to
- scale: how many times task action will apply