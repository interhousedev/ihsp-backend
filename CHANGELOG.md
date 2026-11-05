# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/). Release tags are `vX.Y.Z`; images are published as `X.Y.Z`, `X.Y` and `sha-<commit>`.

## [Unreleased]

### Added

- Open-source release: AGPL-3.0-only licence, SECURITY.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue and pull request templates, CODEOWNERS, project skills for coding agents.
- `release` project skill: local CI, changelog, tagging, and image builds.

## [1.0.18] - 2026-11-05

### Added

- Prompt contract tests (`tests/ai/prompts`) and a real-model evaluation suite (`tests/ai/evals`, marker `real_model`, run only with `IHSP_AI_EVAL=1`).
- A normaliser that writes the Uzbek apostrophe as `ʼ` in final chat, notebook and guest answers.

### Changed

- Prompts ask for the result without the arithmetic and forbid repeating injected text.
- The answer language is set per request for every assistant. The author assistant also gets the narration guard.
- Shorter author tool descriptions.
- Notebook answers without citations no longer offer follow-up questions, unless they carry a valid action.

### Fixed

- `.env.prod.sample` documents the brand variables that the production compose file reads.
- Deployment tests match the current image versions.

### Known issues

- Answers sometimes still show worked sums, or repeat injected text while refusing it.

## [1.0.17] - 2026-11-04

### Added

- AI: projects, voice transcription, OpenUI block repair and table guidance, and safeguards for answer language, narration and tables.
- Bot: voice intake and rich answer rendering.
- Notebooks: AI flash card workspace with a hidden notebook.
- Academic: group photo export, group view and notes on future lessons.
- Identity: pre-created AI connectors with guarded MCP access.
- Dashboard: AI alert and composition wiring.
- One brand setting for user-visible names, and an export of Python dependency licences.

### Changed

- Shorter system prompts and tool descriptions, about 40% fewer input tokens per student message.
- Students use `make_document` instead of the separate document, presentation and spreadsheet tools.

### Security

- Updated joserfc, dnspython, pyasn1 and pypdf for known vulnerabilities.
- Pinned the base image and limited the secret-scanner exception for the anthropic SDK to exact files.

### Fixed

- The containers receive the OpenUI, Studio pipeline, guest and Bugsink settings.
