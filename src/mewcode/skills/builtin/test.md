---
name: test
description: Detect and run the smallest relevant tests without changing product code.
tools:
  - read_file
  - find_files
  - search_code
  - run_command
mode: shared
---
First identify how this project runs tests. If input is present, prioritize the smallest test set matching its description or related changes. Without input, select tests matching current uncommitted changes. Add broader validation when it is reasonably warranted.

Requested focus:

{{input}}

Only run and report tests. Do not modify product code.
