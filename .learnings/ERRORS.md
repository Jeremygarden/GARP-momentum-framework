# Errors

Append structured entries:
- ERR-YYYYMMDD-XXX for command/tool/integration failures
- Include symptom, context, probable cause, and prevention


## [ERR-20260406-001]

**Logged**: 2026-04-06T10:54:21.868Z
**Priority**: medium
**Status**: pending
**Area**: infra

### Summary
edit tool fails when old_string contains non-ASCII characters that got mangled (e.g. 选→선)

### Details
Attempted to edit execution-sop.md using old_string with Chinese text. One character was corrupted (选 became 선) during the first failed attempt, causing exact match failure. Root cause: copy-paste or encoding issue when constructing old_string for edit tool with CJK content.

### Suggested Action
When using edit tool with CJK text, read the file first and copy the exact bytes from the read output. Never retype or paraphrase CJK strings for old_string.

### Metadata
- Source: memory-lancedb-pro/self_improvement_log
---
