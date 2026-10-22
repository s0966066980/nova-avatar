<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Retrospective environment improvements

Add automatic CI for the existing offline integration check, Python tests,
frontend tests, and build. Introduce Python and Vue/JavaScript lint gates
without rewriting bundled third-party engines. Pin the codebase-memory-mcp
project name in repository navigation instructions.

Acceptance: lint gates reject representative errors, existing validation
passes, the Python CI commands work in a clean CPU environment, and new files
retain the Nova Avatar attribution convention.
