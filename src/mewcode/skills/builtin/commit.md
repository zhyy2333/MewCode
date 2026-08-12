---
name: commit
description: Validate relevant Git changes, stage them safely, and create one commit.
tools:
  - read_file
  - find_files
  - search_code
  - run_command
mode: shared
---
Inspect the current Git changes and determine which files belong to this task. Run validation proportional to those changes. Stage only files that are both relevant and safe, write a concise commit message, and create exactly one commit.

Treat the following input as additional commit intent or commit-message constraints:

{{input}}

Do not commit when there are no changes, validation fails, or the intended scope cannot be determined safely. Explain the reason instead.
