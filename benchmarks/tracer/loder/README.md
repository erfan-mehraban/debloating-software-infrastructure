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
  - chown: use fchownat syscall. (*NOTE*: file should exist.)
  - mkdir: create directory
  - remove: delete a file or directory. may use unlink or rmdir syscall
  - rename: rename file or folder and add `-renamed` to it
- files: arrays of files paths which task action should apply to
- scale: how many times task action will apply