<!-- 
Sync Impact Report:
- Version change: [INITIAL] → 1.0.0
- Modified principles:
  - Added: I. Clean & Readable Code
  - Added: II. Security First
  - Added: III. Direct Framework & Library Usage
  - Added: IV. Test-Driven Development (TDD) Mandatory
  - Added: V. Realistic & Comprehensive Testing
  - Added: VI. Simplicity & Root Cause Resolution
- Added sections: Development Standards, Governance Workflow
- Removed sections: N/A
- Templates requiring updates: 
  - ✅ .specify/templates/plan-template.md 
  - ✅ .specify/templates/spec-template.md 
  - ✅ .specify/templates/tasks-template.md 
- Follow-up TODOs: N/A
-->

# CMPE492-Design-and-Implementation-of-a-Robust-LLMOps-Platform Constitution

## Core Principles

### I. Clean & Readable Code
Write clean, concise code focused on readability for your colleagues. Your variable and function names MUST be self-explanatory. Avoid excessive comments; let the code explain itself. Follow senior developer standards.

### II. Security First
Security is highly important for this cloud-based development. You MUST always double-check for client-side exposure. ALWAYS avoid key exposure, as this project will be open-sourced later.

### III. Direct Framework & Library Usage
You MUST use functions and features from a library or framework directly. Do NOT write redundant wrappers or over-engineer solutions around existing built-in features.

### IV. Test-Driven Development (TDD) Mandatory
You MUST use test-driven development in your implementation. The Red-Green-Refactor cycle is strictly enforced: write tests before writing the actual code, run the tests to see them fail (red phase), then implement the code and rerun the tests to observe all of them pass (green phase) before moving to the next task.

### V. Realistic & Comprehensive Testing
Do not only focus on unit tests; you MUST create tests for all user scenarios realistically. Tests shall use realistic environments if possible: prefer real databases over mocks, and use actual service instances over stubs. Contract tests are mandatory before implementation. You MUST NEVER mark a task complete without proving it works.

### VI. Simplicity & Root Cause Resolution
Simplicity First: make every change as simple as possible and impact minimal code. Do not over-engineer. No Laziness: find root causes instead of applying temporary fixes. Always ask yourself: "Would a staff engineer approve this?"

## Development Standards

Code must be clean, concise, and understandable without relying on excessive comments. TDD is required. Testing must be realistic, avoiding mocks and stubs where possible. Use libraries and frameworks directly; avoid wrappers.

## Governance Workflow

All development must align with the Core Principles. Amendments to this constitution require a version bump following semantic versioning rules:

- MAJOR: Backward incompatible governance/principle removals or redefinitions.
- MINOR: New principle/section added or materially expanded guidance.
- PATCH: Clarifications, wording, typo fixes, non-semantic refinements.

**Version**: 1.0.0 | **Ratified**: 2026-03-23 | **Last Amended**: 2026-03-23
