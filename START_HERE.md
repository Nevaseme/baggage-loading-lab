# Start here

This workspace supports packing research and preserves submission evidence. Follow the current request and [AGENTS.md](AGENTS.md); read only the references needed for the task.

For an AI opening this repository for the first time, start with
[current state and development history](docs/ai-handoff.md), then
[submission bundles](deliverables/README.md). The repository now includes the
project's simulator source, experiments, failed approaches, and historical plans.

| Task | Start with |
| --- | --- |
| Improve an algorithm | [Development guide](docs/development.md), [packing evidence](knowledge/lessons/packing-evidence.md), relevant source |
| Compare results | [Generated results](progress.md), linked evaluation records and raw feedback |
| Prepare a submission | [Agent contract](contracts/agent-interface.md), [evaluation contract](docs/evaluation-contract.md) |
| Record a submitted ZIP and result | [Registry operations](docs/registry-operations.md) |
| Find historical work | [Documentation map](docs/README.md) |

For a candidate handoff, provide the technique name, parent candidate, source revision, ZIP/hash, and measured results. Include the next unresolved decision. A ZIP created without simulator runs is ready for local evaluation, not yet verified for submission.

For a compact offline handoff, use `tools.lab export-context` and identify the
revision in `REGISTRY.json`; `FILE_HASHES.json` identifies its files. That compact
export is not a full workspace backup. Use the repository for complete project
history. Exact submissions and their result logs live together in `deliverables/`
and are linked to registry records; Release assets provide an additional copy.
Reconstructed historical source bundles are identified separately in the [README](README.md).
