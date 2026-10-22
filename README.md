<p align="center">
  <img src="docs/readme/assets/hero.svg" alt="NextRelay — keep your project moving across AI sessions" width="100%">
</p>

<h2 align="center">Conversations end. Progress continues.</h2>

<p align="center">A general-purpose AI work management and coordination platform.<br>Keep project outcomes, task progress, and working context together across sessions.</p>

<p align="center">
  <a href="#see-the-workflow">Demo</a> ·
  <a href="#inside-nextrelay">Architecture</a> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="docs/ui/t11-real/tasks-real.png"><img src="docs/ui/t11-real/tasks-real.png" alt="Real local workspace: task state, acceptance evidence, and an exact-version document reader" width="100%"></a>
</p>

## Your next session should start with the work you already did

A new AI conversation starts, and you explain the project again. Several sessions move forward at once, and their outcomes end up in different places. What changed? Which task is blocked? Which decision still applies?

**NextRelay is designed to make that project history usable.** Bring in the outcomes you choose to share, understand where the project stands, and prepare for the next step.

- **Keep working in familiar AI tools.** One platform or several; one session or many. You do not need NextRelay to launch a session or require a particular prompt or Skill.
- **Bring the work together.** The product design connects outcomes, documents, versions, and evidence to the project they belong to.
- **Understand the next step.** Tasks and dependencies make progress, blockers, and parallel work easier to inspect.
- **Keep decisions deliberate.** A session ending is not task acceptance. Candidate changes, review, and formal commits are separate steps.

Project state reflects the materials provided and their stated evidence. NextRelay does not silently collect conversations or continuously monitor external sessions.

## See the workflow

### 1. Bring session outcomes into the project

Choose the materials, inspect the processing scope, and see a result for each item.

[![Synthetic prototype: select an import batch, review consent, and inspect per-item results](video/out/gifs/01-import-results.gif)](video/out/gifs/01-import-results.gif)

*Current local delivery supports file upload and format parsing.*

### 2. Review what should change

Inspect the proposed state, its source, and its impact before confirming a change.

[![Synthetic prototype: inspect a candidate change and its evidence before confirmation](video/out/gifs/02-review-changes.gif)](video/out/gifs/02-review-changes.gif)

*Prototype confirmation reaches “awaiting acceptance.” In the real local workspace, saving a candidate, reviewing it, and formally committing it are distinct operations; uploads do not automatically generate candidates.*

### 3. Find dependencies and the next step

Move between the task list and graph to inspect prerequisites, blockers, and executable work.

[![Synthetic prototype: inspect task dependencies and filter the next executable work](video/out/gifs/03-task-dependencies.gif)](video/out/gifs/03-task-dependencies.gif)

## What works today

Current code: **nextrelay 0.7.0 · schema v7**. This is a local development implementation for synthetic materials, with a separate in-memory prototype.

| Area | Current delivery |
| --- | --- |
| Projects and files | Create/select projects, upload local files, inspect per-item results, and retry failed items. Local format support: TXT, Markdown, protocol JSON, and static HTML. |
| Documents and evidence | Read saved content, named sources, exact artifact versions, and associated evidence. |
| Changes and history | Save existing-service candidates, review them, commit approved changes, and inspect history and single-change compensating reversal. |
| Tasks and dependencies | Read task lists/graphs and dependency state; existing services support task lifecycle, review, limited checks, and human acceptance. |
| Persistence | The real local mode uses SQLite and an explicitly selected originals directory. The synthetic preview uses memory and resets on refresh. |
| Not connected | Automatic semantic extraction/matching/merging, model processing, GitHub repository reading, cloud storage, and Context Sync. Deletion/recovery and full development-readiness flows are also incomplete. |

The local subset is not a completed MVP or a production service; no performance or production-readiness claim is implied.

## Three parts, one continuing project

### Project Black Box — keep the story and its evidence

The product module for bringing user-provided session outcomes together with sources, decisions, and change history. It proposes traceable updates rather than silently changing formal state.

**Today:** local ingestion, content/source/version reading, and reviewed change services provide part of this foundation. Automatic semantic organization and merging are pending.

### Control Tower — understand where the work stands

The product module for task relationships, progress, dependencies, and blockers. Tasks are the graph nodes; prerequisite relationships are its edges. Sessions, attempts, and artifacts can be associated with tasks.

**Today:** the local workspace exposes task lists, a task graph, dependency state, and existing lifecycle/review services. The graph describes work relationships; it does not execute external AI agents.

### Context Sync — prepare the next conversation

The planned module for retrieving current project state and preparing context when a user needs a handoff. The design separates effective context from unresolved reminders.

**Status:** available as a synthetic interaction prototype only. The real local workspace has no Context Sync generation or copy service. [View the prototype clip](video/out/gifs/04-context-handoff.gif).

## How the pieces fit

[![Product workflow with current local steps and planned semantic processing and context handoff explicitly distinguished](docs/readme/assets/workflow.svg)](docs/readme/assets/workflow.svg)

The workflow is: work in your AI tool → provide outcomes → organize proposed updates → review changes → inspect project state → continue working, with a context handoff when needed. Automatic organization and real Context Sync remain planned.

## Inside NextRelay

| Layer | Current implementation |
| --- | --- |
| Workspace | HTML/CSS and vanilla JavaScript; a real `LocalAdapter` and a separate in-memory `SyntheticAdapter`. |
| Local application | Python 3.14 standard-library WSGI service, bound to `127.0.0.1`; temporary development Bearer authentication. |
| Business state | SQLite transactions, project revision checks, separate candidate/review/commit operations, and persistent request receipts. |
| Originals | An explicitly selected local directory, with per-file processing and retry history. |

Three mechanisms matter to the product experience:

- **Sources and exact versions:** inspect which material supports a state or decision.
- **Review before formal state changes:** a proposed update is not already an accepted fact.
- **Explicit uncertainty:** incomplete imports, unavailable capabilities, and writes awaiting confirmation remain visible.

**License:** this checkout has no root project license file. Project-wide redistribution terms have not been declared here.
