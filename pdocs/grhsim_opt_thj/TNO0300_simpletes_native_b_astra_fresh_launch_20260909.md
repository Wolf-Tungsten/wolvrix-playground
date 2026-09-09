# SimpleTES native-B Astra fresh research launch

## Scope and baseline

The user authorized a new SimpleTES research run on node030 with
`gpt-6-astra`, reasoning effort `max`, THJ credentials, and the latest Codex.
This is a fresh tree, not a continuation of the pre-B research checkpoint.
The executable baseline is the native-B default established in
[TNO0296](./TNO0296_simpletes_b_native_landing_20260909.md) and
[TNO0297](./TNO0297_simpletes_b_native_baseline_handoff_20260909.md).

Actual identities recorded in the launch manifest:

- SimpleTES: `4ca31aa48497dd17afa1c6626e21d806dcd92d86`.
- Pinned parent executable snapshot: `fd54f8deab18d861cd29fa4c3852f1013c3948f1`.
- Pinned Wolvrix: `94109bc68e0f0ea76d6083b3c193750be9a7bfae`.
- Empty native-B seed digest: `a8b734f3e8acef1ecaddebdd14e35aa65e1864be5d045e0a6b3c25a1ce72f6ab`.

The seed has no patch or option overrides. B is already part of the general
Wolvrix default; A/C are not included. This run gets a fresh control and slot
namespace, without reinterpreting old control binaries or old scores.

## Codex and model configuration

The node030 system Codex was `0.145.0`. At launch, npm's stable `latest` tag
for `@openai/codex` resolved to `0.153.4`. That version was installed into an
isolated prefix and its actual `--version` output was `codex-cli 0.153.4`:

```text
/nfs/home/tanghaojin/.local/share/simpletes/tools/codex-0.153.4/node_modules/.bin/codex
```

The launch environment prepends this directory to PATH, so the capability
preflight and subsequent generation workers use the same CLI. The system
installation was not overwritten. The [official Codex CLI documentation](https://learn.chatgpt.com/docs/codex/cli)
and [GPT-6 Astra model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra)
were consulted for CLI setup and model/effort support. The live preflight,
not documentation alone, verified compatibility with the configured THJ API.

The source configuration remains `~/.codex/config.thj.toml`, and the auth
file remains `~/.codex/auth.thj.json`. Because the existing config names
`gpt-5.6-sol` and SimpleTES requires config/CLI model identity to agree, a
TOML-parser-derived private run copy changes only `model` to `gpt-6-astra`
and retains `model_reasoning_effort = "max"`. Provider, endpoint, auth
behavior, service tier, and all other settings are preserved. The original
config/auth files are unchanged; no key is placed in documentation or Git.
The private config is mode `0600`, under a mode `0700` run directory.

The native model catalog is used. No K3-specific prompt suffix, custom model
catalog, or K3 subagent-count restriction is passed. No context-window or
automatic-compaction override was added. No production SimpleTES source
change was needed for this launch.

## Runtime settings and evidence

- Host: `node030.bosccluster.com`.
- Model / effort: `gpt-6-astra` / `max`.
- Budget: `max_generations=64`, `max_valid_evaluations=32`.
- Workers: `4 gen / 1 eval`; selector `rpucg`, four chains; reflection off.
- Generation timeout: `10800 s`; evaluation timeout: `21600 s`.
- Infrastructure retries: `GRHSIM_INFRA_RETRIES=99`.
- Codex exec retries: `2`; capacity/transient continue budgets: `3` each.
- Build bounds: GrhSIM/VM jobs `4`, CMake/package/OpenMP jobs `8`.
- Every launch command sources the playground `env.sh` first.

The existing SimTop 50k walltime protocol remains unchanged: fixed ASLR,
strict quiet-CCD admission and runtime audit, same-CPU mirrored
`ABBABAAB`, page-local staging, order-gap and schema-v4 stability gates.
Control self-bias must pass before the initial score is normalized to `1.0`.
Runtime infrastructure retries retain the existing proof-backed binary reuse.

The offline launcher dry-run passed. The actual launcher then reported:

```text
GrhSIM evaluator toolchain preflight passed: compiler=/usr/bin/clang++, scanner=/usr/bin/clang-scan-deps-19, major=19
Codex capability preflight passed: model=gpt-6-astra, effort=max, repo_tool_calls=1, model_catalog=native, response_chars=632, response_sha256=7f89a5f36d0f7089a2d50124e6351858afb0169c51cee76964a864cd9bb4d53c
```

This is a real model invocation that exercised repository tooling. Full bench
tests were not rerun for a configuration-only launch; the prior native-B
handoff's 161-test result is recorded in TNO0297, not claimed as a new result.

## Process and artifact locations

Run root:

```text
/nfs/home/tanghaojin/wolvrix-SimpleTES-workspace-5/SimpleTES/checkpoints/grhsim_simtop_50k/hot_dispatch_b_gpt6astra_max_fresh_node030_20260909_225353
```

Files relative to that root:

- `launch_manifest.json`: actual command, source pins, CLI/config/script identities.
- `config.thj.astra.toml`: private model-specific THJ config copy; do not commit.
- `dry_run.log`: offline launch validation.
- `launcher.log`: real capability preflight and engine startup output.
- `supervisor.json`: launch timestamp and process identities.
- `2026-09-09/instance-ed572ae5/run.log`: research engine log.

The supervisor started at `2026-09-09T22:59:27+08:00` in tmux session
`simpletes-astra-20260909_225353`. Supervisor/launcher/engine PIDs were
`2133861 / 2135165 / 2152149`. The node-local slot root is
`/tmp/simpletes-grhsim-post-hot-dispatch-b-astra-node030-20260909_225353`,
with pin-derived namespace `99aebe247c97e44f/slot-0`.
The one-shot supervisor is
`build/astra_launch_20260909/launch.py` at workspace level. It holds a
launch lock, waits for the launcher, and records its exit rather than
automatically creating another research instance.

At `23:04 +08:00`, all three processes were alive, the engine had initialized,
and the initial control evaluator was preparing its fresh build. There were
no candidate scores or accepted new walltime measurements yet. This record
therefore makes no new performance claim; the previous B landing regression
in [TNO0299](./TNO0299_simpletes_b_native_walltime_regression_20260909.md)
is separate from this run's pending initial control.
