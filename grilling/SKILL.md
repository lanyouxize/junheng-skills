---
name: grilling
display_name: Grilling
description: Grill the user relentlessly about a plan, decision or idea until you reach a shared understanding. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrase.
description_zh: 方案/决策/想法当决策树逐轮拷问至共识：每轮只问已定前提的问题并附推荐答案；事实自查、用户拍板，共识前不动手。触发：拷问我、质询我、审问、grill me/third degree/interrogate、压测这个方案、压力测试、极限情况、这设计哪里会翻车、隐患、靠不靠谱、先问清楚再动手、问明白。
version: 1.0.0-local.1
---

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round.

Format a round like so:

```
❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>

---

❓ **Q2** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>
```

Word each question so "yes" accepts your recommended answer.

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.

## Hard guards

An empty frontier is **not** permission to build. Confirm shared understanding, then stop and wait.

**Never answer your own decisions.** Facts you fetch; decisions the user makes. Resolving your own questions as a shortcut is the most common way this skill fails.

**Always recommend, and recommend honestly.** Every question carries a `➡️` answer. When your recommendation argues _against_ the question as worded, say so — agreeing with the recommendation can mean answering "no", and the user needs to know that.

**Stay stateless.** This interview writes no files. Recording decisions as `GLOSSARY.md` or ADRs belongs to `grill-with-docs` — a sibling skill that is not installed here; if it is absent, simply write nothing.

**Reopen, don't patch.** If two questions in a round turn out to depend on each other, the frontier was miscalculated — reopen the affected branch next round instead of quietly reconciling it.

## Boundaries

Read `references/boundaries.md` when any of these happens: a question cannot be settled by talking, the session keeps growing, context is getting long, or the user says "just do it" / "you decide".

Read `references/rounds-template-zh.md` when the interview is conducted in Chinese.
