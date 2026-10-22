<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Code navigation

Use the codebase-memory-mcp project `nova-avatar` for this repository. Its root
is `/home/oliver/nova-avatar`. The service also has an index named
`home-oliver-nova-avatar` for the same root; routine application-code queries
should use `nova-avatar` consistently.

When refreshing the index, pass `repo_path="/home/oliver/nova-avatar"` and
`name="nova-avatar"` to `index_repository` so the refresh updates the selected
project instead of creating another name.

If project discovery is necessary, filter `list_projects` results by this
repository's root and return only the matching names, roots, and Git metadata.
Inspect one representation of the result (`structuredContent` when available)
instead of printing both structured data and text content.

Graph results are navigation aids. After edits or a checkout change, refresh
the index when results no longer match the working tree; use current file
contents for exact edits. Configuration and other non-code files can be read
directly, as described by the global graph-tool guidance.
