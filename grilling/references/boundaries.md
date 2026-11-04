# Boundaries

Read this when the interview is not behaving like the happy path. Nothing here changes the mechanism in `SKILL.md`; it only covers what to do at the edges.

## A question that talking cannot settle

Some questions cannot be answered by talking at all — "one long page or three?", "how should this interaction feel?". More grilling will not get you there: you will rephrase, the user will guess, and the scope will grow with the uncertainty.

Stop the interview. Build the throwaway version instead, have the user look at it, then come back and answer in one line. Reopen the frontier at that branch and continue.

## The session keeps growing

There is deliberately **no question cap** — three questions and fifty questions are both legitimate, and a fixed ceiling either truncates the hard case or feels arbitrary on the easy one.

The control is plain language, and it is the user's call: tell them to wrap up, or accept the plan where it stands.

When a session runs very long, the cause is almost always that the scope was too big. Say so, and propose splitting the work into pieces that can be grilled separately. Do not keep asking into an oversized tree.

## Context is getting long

Past a certain length the questions get worse, not better — later rounds start contradicting or repeating earlier ones. When you notice that, stop and say so: summarise the decisions settled so far, name what is still open, and let the user decide whether to wrap up, split the scope, or continue in a fresh session.

## You have no basis to recommend

Every question carries a `➡️` answer, but a recommendation is not a preference. Recommend when you have grounds — an existing project convention, a stated priority, a clearly safer or cheaper option — and give the reason in a few words.

When you have no grounds, say plainly that this is a default rather than a recommendation, and let the user own the choice rather than anchoring them to your taste.

## The user answers "just do it" / "you decide"

Treat that as authorisation to use a sensible default, not as permission to guess at the whole tree.

If the remaining decisions are low-risk and easy to revise, stop asking, state the one or two assumptions that actually shape the outcome, and finish.

If a remaining decision is irreversible, externally visible, or expensive, keep that one question. Do not re-ask the parts they just delegated.

## "One question at a time"

The round format is the default. Upstream documents a line in a global `CLAUDE.md` as the opt-out; on this host there is no global config file to edit (verified: no `CLAUDE.md` and no `AGENTS.md` exists), so the opt-out is stated in the session instead. Say it once and the rest of the interview follows it.

## The user pushes back

Pushback is the point, not a failure. When they reject a question as too shallow, or say the scope is drifting, or answer "I don't know":

- too shallow → go one level deeper on that branch next round;
- scope drifting → re-cut the tree and say what you dropped;
- "I don't know" → that is a real answer, and it usually means the branch needs a prototype rather than another question.

## Ending

Say what was decided, confirm that understanding is shared, and wait. Whether to carry the result into a spec or a build is the user's next move — not this skill's. The blocking rule itself lives in `SKILL.md`; it is not repeated here.
