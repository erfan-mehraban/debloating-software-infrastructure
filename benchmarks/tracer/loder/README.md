# Loder
is a command line tool to apply read/write/execute files as configured in tasks yaml file.

## Task yaml file structure

Containes an array of tasks with the following keys:

- kind: what kind of tasks should be executed.
  - read: read first 4 bytes of files
  - ...
- files: arrays of files paths which task action should apply to
- scale: how many times task action will apply