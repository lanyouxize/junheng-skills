---
name: grill-me
display_name: Grill Me
description: 'A relentless interview to sharpen a plan or design. User-invoked entry point: it runs a grilling session.'
description_zh: 用户显式调用的入口：对方案或设计发起一场不留情面的拷问，直到达成共识。当用户说「grill me」「拷问我」「拷问我的方案」时使用；AI 不得自行发起。
version: 1.0.0-local.1
disable-model-invocation: true
---

Call the Skill tool with "grilling".

## Hard guards

**User-invoked only.** Reach for this skill when the user asks to be grilled. Do not start a session on your own initiative, and do not start one mid-task — it belongs in a fresh conversation, not stacked on a plan that was already written.

**Confirm the engine loaded.** This skill is only a pointer; the interview itself lives in `grilling`. If `grilling` has not loaded, load it before asking anything — otherwise you will improvise an interview and the round format, the frontier, and the recommendations will all be missing.

**Stay stateless.** No files are written. The only output is a clearer idea in the user's head.
