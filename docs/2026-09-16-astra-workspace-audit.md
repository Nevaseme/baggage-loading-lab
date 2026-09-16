# Astra workspace audit — 2026-09-16

The user requested shorter English instructions, removal of obsolete process, and freedom to rebuild for competitive performance. A later instruction explicitly extended the work to algorithm optimization.

## Changes and rationale

- Reduced the root agreement to project-specific objectives, authority, evidence, and task-based references.
- Replaced the compulsory reading sequence with a task router; rewrote the current reference documents in English.
- Kept submission promotion requirements in one document. Routine edits use relevant checks without repeating the full submission campaign.
- Corrected the instruction to update generated `progress.md`: registry records produce results tables; experiment notes hold development decisions.
- Marked historical entry points and retained their original contents. Prior model assignments, report templates, and pause/phase instructions no longer govern new work.
- Added a development map identifying source, reviewed components, partial work, and usable runtime commands.
- Removed fixed legacy model/effort assignments. Delegation now follows the complexity and cost of the actual work.
- Replaced inherited universal 6 s/5.5 s timing gates with official limits and measured runtime margin. Current experiments retain their declared 5.2-second search budget; prior outcomes are unchanged.

## Workspace findings

The inventory covered every top-level directory, including ignored local code. At audit start Git tracked 65 files; 28 older plans/specifications were already untracked. The local simulator contained 8,572 files (269 MB), including dependencies and cached files. `.superpowers/` held 77 Markdown records plus traces and snapshots. Dependencies and old results remain useful for reproduction, so deleting them would not improve experiments.

The registered best exact Public score is 29.74350010538. Four lineages have stopped external runs. Historical evidence identifies both unchecked fallback actions and excessive rejection of safe placements. The reviewed shield preserved 25 safe placements; the scaffold/portal successor remains incomplete. These findings motivate coverage and validation experiments, not a presumption that the existing architecture should survive.

Ubuntu WSL with `PYTHONPATH=.:tests:.test_deps_linux` supplies working physics dependencies. The Windows virtual environment can run registry tooling but lacks those dependencies. The runtime probe succeeded after normal tool permission escalation.

## Official guidance applied

[Model guidance](https://developers.openai.com/api/docs/guides/latest-model) supports explicit completion, relevant delegation, and proportionate verification. [Rethinking skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra) recommends narrow instructions and references loaded when useful. [AGENTS.md documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md) explains how project instructions enter the instruction chain. These sources were opened on 2026-09-16.

Installed Superpowers procedures were reviewed and applied in proportion to the task under the user's existing project preferences. Shared plugin caches and app settings were left intact; this audit changes project guidance and working files.

Validation results and algorithm experiments are recorded separately under `experiments/` and in the final handoff. Documentation changes alone do not establish a score improvement.

## Verified outcome

The registry and benchmark standard-library suites pass 60 tests. Active-document
links and registry validation pass; all 174 protected original files retain their
hashes. The root agreement is 344 words, down from 757. Native recovery improves
one of three mode-C comparisons and ties two; offline and raised-release variants
are rejected on measured results. [Current experiments](../experiments/README.md)
record the retained comparison point and the next technical decision.
