# 013 — Prompt ladder & the model-prompt compatibility database

**Status:** Living document — started 2026-08-05 (user-proposed methodology)

## The idea

Tier-1 proved models can execute a fully-engineered prompt. Real humans
don't write engineered prompts. The ladder measures the GAP: start every
passing model at a lazy, vague, distractor-laden prompt, and each time it
fails, add ONE specific clarifier targeting that failure class — until it
succeeds. The rung where it succeeds is that model's **prompt demand
level**. The output is a public example database: which prompt phrasing
works with which model, backed by real runs.

Key insight: the tier-1 gauntlet prompt is scar tissue — every phrase in
it was added because some model failed without it ("FILESYSTEM only"
= granite's document-world; "verify for real" = fabricated ls; "do not
stop until" = one-file victory laps). The ladder decomposes it back into
its individual scars and asks which ones each model actually needs.

## Rungs

- **R0 — lazy human** (verbatim, typos kept):
  "build me a website for my local business, i want to have it pretty its
  for a coffee shop so i want you to get open source images from the net,
  i also want you make it with react etc"
- **R1..Rn — one clarifier per observed failure class.** Never add two
  clarifiers at once; a rung tests exactly one repair. Established
  clarifier catalog (from tier-1 scar tissue):

| Failure class | Clarifier to add |
|---|---|
| outputs code in chat, saves nothing | "make sure they are files i can access on the filesystem" |
| document-world escape | "do not use documents — a document is not a file" |
| scattered/no project dir | "put everything in one folder named X" |
| fabricated verification | "verify for real: run ls and show the output" |
| stops after one file | "do not stop until ls shows all N files" |
| asks questions instead of working | "do not ask questions" |
| ignores tools entirely | name the exact tools ("with bash and write_file") |
| react/npm cliff | accept CDN-react as pass, or clarify "plain html/css/js is fine" |
| images cliff | accept hotlinks as pass, or clarify "link images by URL, do not download" |

- Grading stays real-data only: files on disk, sizes, tool logs. Full
  protocol per run: preflight runs EMPTY, drain before grading (doc 012
  measurement rules).

## Deliverable

`prompt-database`: per model — its demand level, the exact minimal prompt
that works, the failure specimen at each rung below it. Format TBD
(likely a doc table + JSON for the app to consume — could eventually
power a per-model prompt-hint in the UI, which is the real payoff:
Odysseus auto-appending the clarifiers a model is known to need).

## Predictions on record

- User: qwen wins most rungs at R0 (largest + coder-tuned). "But who knows."
- Assistant (2026-08-05, deepseek R0 in flight): most models need R1-R2;
  react cliff fails at R0 for everything except possibly qwen3-coder and
  gpt-oss (npm-provens); images cliff resolves as hotlinks not downloads.

## Fleet freshness (user observation, 2026-08-05)

Several installed models are outdated — IBM granite has 4.1 now; others
have newer releases. Before the ladder campaign: inventory installed vs
latest on Ollama library, refresh where a newer family member exists,
note that ladder results are per model VERSION (the database must record
exact tags).

## Results log

- 2026-08-05 — R0 launched: deepseek-r1:14b (lazytest session, full
  protocol). Predictions above.
