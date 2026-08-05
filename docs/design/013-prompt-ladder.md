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

- **R0 — lazy human, USER-AUTHORED 2026-08-05 (official, verbatim, typos
  kept — supersedes the earlier template for the fleet sweep):**
  "build me a website for my local business, i want to have it pretty its
  for a company called Kaffe on the Moors so i want you to get open source
  images from the net, i also want you make it with react vite, whatever
  you need. i want it to have the price of the different coffees, and each
  coffee will have its own image. i want you to come up with text for each
  coffee type with exxaggerated speech like ''this coffee was lovingly
  handcrafted by local farmers in X country and roasted by our expert
  roasters to bring out the notes this coffee gives.''  and for coffee
  that contains milk or chocolate to do something similar."
  Notable: demands SPECIFIC content (per-coffee prices, images, marketing
  copy) — directly punishes the scaffolds-forever class; a scaffold with
  boilerplate scores zero content.
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

## Endgame (user, 2026-08-05): profiles dissolve into the database

With enough models × observed tool-calling behavior, hand-curated
profiles become unnecessary: the parser already knows which pattern fired
every round — persist that per model tag and dialect detection becomes
lookup + statistics, not match keys. dialect_profiles.py then shrinks to
a CACHE of learned conclusions. What survives of "profiles": (a) cold
start — first contact with an unknown model triggers the P1-P3 auto-probe
battery and the model classifies itself; (b) interventions (turn notes,
fenced fallback) are treatments with failure costs, not observations —
they need confidence thresholds before auto-adoption, though treatment
selection itself is learnable from rematch completion rates. This doc's
database and doc 012's specimens are the first tables of that system.

## Results log

- 2026-08-05 — R0 launched: deepseek-r1:14b (lazytest session, full
  protocol). Predictions above.
- 2026-08-05 — **R0 deepseek-r1:14b: fails, but not where predicted.**
  The react cliff DIDN'T stop it: 23 npm + 9 npx + 3 yarn + 2 node calls,
  a real `npx create-react-app` TypeScript scaffold with node_modules on
  disk (third npm-capable surprise after gemma4). What failed:
  - **NEW FAILURE CLASS — scaffolds forever, never writes content.** The
    CRA App.tsx is untouched boilerplate; zero coffee-specific code
    anywhere. All rounds went to toolchain theater.
  - No project coherence: THREE roots (coffee-shop/, coffee-shop-website/,
    plus husk files strewn at workspace root — 0-byte HeroSection.jsx).
  - Images requirement ignored (no curl/wget/web_search calls).
  - Also: 1 sudo attempt, JSX pasted into bash fences (2× exit 127).
  - Run self-terminated (~640s drain) — no lingering this time.
  Candidate R1 clarifiers: "put everything in one folder named X" +
  "content first: write the actual pages before any toolchain setup".
  Ladder table gains the scaffolds-forever row.
