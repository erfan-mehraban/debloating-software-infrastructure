# Loder
is a command line tool to apply read/write/execute files as configured in tasks yaml file.

## Task yaml file structure

Containes an array of tasks with the following keys:

- kind: what kind of tasks should be executed.
  - read: read first 4 bytes of files (beaware of kernel cache)
  - direct-read: read first 4 bytes of files and bypass kernel cache
  - write: write 4 bytes in a file
  - direct-write: write 4 bytes to the files directly
  - execute-subproc: run another binary (execve syscalls)
  - execute-subthread: run a binary in a os thread
  - create-delete: create a file and then delete it
  - fork: fork a procces. use fork + clone + vfork syscalls
  - chmod: use fchmodat syscall. (*NOTE*: file should exist.)
  - chown: use fchownat syscall. (*NOTE*: file should exist.)
  - mkdir: create directory
  - remove: delete a file or directory. may use unlink or rmdir syscall
  - rename: rename file or folder and add `-renamed` to it
  - hard-link: create hard link for file inode in the target directory with `-hard-link` appended (*NOTE*: file should exist.)
  - soft-link: create symbolic link for files in the target directory with `-soft-link` appended (*NOTE*: file should exist.)
- files: arrays of files paths which task action should apply to
- scale: how many times task action will apply