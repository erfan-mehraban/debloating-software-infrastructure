# Loder
is a command line tool to apply read/write/execute files as configured in tasks yaml file.

## Task yaml file structure
Containes array of tasks which has these keys:
- kind: what kind of tasks should execute
  - read: read first 4 byte of files
  - ...
- files: arrays of files paths which task action should apply to
- scale: how many time task action will apply
