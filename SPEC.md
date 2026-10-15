# mujoco-agent — SPEC v0 (2026-10-15)

## Goal

A closed loop in which an agent builds, runs, sees, judges and fixes a MuJoCo
robot demo end to end, headless, on agent-next sandboxes. The bar: someone with
only ChatGPT or Claude plus our sandbox connector (`mcp.agent-next.com/mcp`)
and the `mujoco` sandbox image can produce a complex robot demo (video +
receipt) without touching a terminal.

## Why this repo

- Official MuJoCo ships agent *knowledge* (`google-deepmind/mujoco/doc/skills`,
  six SKILL.md guides since 2026-09-14) but no runtime tools and no MCP.
- Community MCP servers are small (all under 10 stars) and unjudged; the
  nearest agent-native simulator, omnisim, is Newton-first and documents no
  record/replay/diff and velocity-less snapshots.
- What is missing is the runtime loop — load, run, observe, judge, reproduce —
  and that is what this repo owns. Knowledge stays with the official skills.

## Non-goals

- Re-writing MuJoCo docs as skills (bundle the official ones instead).
- Hand-rolled controllers, RL wrappers, multi-robot coordinators or
  LLM-sampling "natural language control" (the legacy modules; callers write
  control code, the loop judges it).
- Desktop viewers as a requirement; everything must work headless.
- Building articulated robots in Blender (robots come from Menagerie/URDF;
  Blender supplies scenes, props and cinematic re-renders).

## The loop

```
intent -> plan -> build scene -> run -> observe -> judge --pass--> ship
            ^                                          |
            +------------------ fix <------- fail -----+
```

| step | mechanism | state |
|---|---|---|
| plan | official skills + recipe library (from W1-W3 below) | skills exist; recipes to build |
| build | Menagerie, MjSpec, Blender asset -> MJCF (obj2mjcf + coacd) | pieces exist, no single command |
| run | `mujoco-agent run` / `run_until` (time, event or predicate) | to build |
| observe | keyframe strips (PNG), metrics, contact events with completeness | sandbox already returns PNGs as MCP image blocks |
| judge | per-recipe predicate oracle + cross-model VLM frame check | to build — the gap that decides whether the loop closes |
| fix | `diagnose` (instability, penetration, solver divergence) | to build |
| ship | lossless MP4, receipt, live 3D via Studio `launch_web` on a sandbox preview URL | ffmpeg + preview URLs exist |

## Interfaces

One core, three front doors that return the same JSON:

- CLI `mujoco-agent <cmd> --json` — what web-chat users reach through
  `sandbox_exec`, and what workers/CI call.
- MCP stdio server — for Claude Code / Codex / Cursor inside or next to the
  sandbox.
- HTTP (later) — so the sandbox gateway can pass the tools through to
  ChatGPT/Claude web without exec.

Tool surface (about 15, replacing the five overlapping legacy servers):
`load`, `edit` (MjSpec patch + recompile), `step`, `run_until`, `inspect`,
`render` (rgb/depth/seg, EGL), `events`, `checkpoint`/`restore` (full
`mj_getState`, velocities included), `record`, `replay_diff`, `validate`,
`diagnose`, `judge`, `capabilities`.

## Plan

Official ecosystem first, our layer second: each official tutorial has known
outputs, so each becomes a recipe whose expected output is its judge, and the
steps agents fail on become the tool list.

| wave | content | done when |
|---|---|---|
| P0 | repo transfer + rename, honest gate (this PR) | verify.sh + CI green on the ratchet |
| W1 CPU | `python/tutorial`, `mjspec`, `rollout`, `LQR`, `least_squares`, `sysid`, dm_control tutorials; render all 73 Menagerie models | notebook runs clean with key numbers matching upstream; every model loads and renders a non-empty frame |
| W2 GPU | MJX tutorial + `training_apg`, MJWarp tutorial + Apollo locomotion, Playground locomotion/manipulation/vision/dm_control notebooks | reward at the notebook's published level + policy video |
| W3 interactive | Studio `launch_web` and the WASM demo app on sandbox preview URLs; aloha_sim; mujoco_mpc | preview URL shows the live scene |
| P1 | core + CLI + MCP for load/run/observe, driven by W1-W3 failure stats | same JSON from CLI and MCP; fresh-env `uvx` install |
| P2 | checkpoint/record/replay_diff/diagnose/judge | bit-identical replay from seed + checkpoint |
| P3 | demo kit: Blender scene -> MuJoCo, omnisim/Newton comparison demo, sandbox template wiring | demos listed on the sandbox gallery |

Every recipe is executed by a fleet worker through the outsider path only
(`sandbox_exec` + `sandbox_files_read`), so each run is also a usability test.

## Acceptance oracle

1. Outsider test: fresh ChatGPT and Claude accounts, five prompts of rising
   difficulty (L1 pose + render, L2 scripted pick-and-place, L3 legged
   locomotion with a bundled policy, L4 Blender scene + multiple robots, L5 new
   skill training); record success, turns, wall time and human interventions.
   Run once on the current image as the baseline, then after each wave.
2. Every shipped video passes the sandbox `video_gate.py` motion gate and a
   cross-model frame review.
3. `.claude/verify.sh` green; new core coverage >= 90%.

## Legacy suite

The pre-rewrite tests are known red at 4da0698 (146 passed / 72 failed / 8
errors; several tests import classes that never existed, others target the old
`mcp.Server.list_tools` API; the combined run segfaults, per-file runs do not).
`scripts/legacy_ratchet.py` runs each file in its own process and fails if
passes drop or failures/errors grow versus `tests/LEGACY_BASELINE.json`. It is a
floor, not a target: legacy modules are retired as the new core lands, and the
baseline is lowered only in the same change that removes them.

## Inputs and salvage

- The pre-transfer local checkout (6 commits and an uncommitted v0.9.0
  "unified ecosystem" tree not on origin) is archived with a verified restore at
  `agent-next/archives/mujoco-mcp-old-checkout-20261015/` (git bundle of all
  refs, `uncommitted.diff`, tarball, SHA256SUMS) and its local main is on branch
  `archive/local-main-20251021`. Salvage is decided per item during P1; nothing
  is merged wholesale.
- Existing sandbox images: agent-infra `templates/mujoco` (MuJoCo/MJX/Warp
  3.15, Playground, Menagerie pinned), `templates/gpu-robotsim` (MuJoCo, Warp,
  Playground, Genesis, Newton, PyBullet, RoboSimStudio; stdio MCP),
  `templates/gpu-mjwarp`, `templates/blender`, `templates/gpu-blender`.
- Official skills to bundle: MuJoCo `doc/skills` (6), NVIDIA/skills
  (`ovnewton-usage`, Warp skills), IsaacLab `.agents/skills`.

## Risks

- GPU leases have no network and run Python 3.13; Playground first runs fetch
  assets and build JAX caches — W2 must confirm what the image pre-bakes.
- Sandbox lifetime is a hard cap (exec does not extend it); size timeouts to
  the whole job for training runs.
- Control, not physics, is what breaks complex demos; L3+ depends on bundled
  policies and IK/planning blocks, not on more tools.
