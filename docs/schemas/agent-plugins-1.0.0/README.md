# Agent Plugins 1.0.0 schema snapshots

`plugin.schema.json` and `mcp.schema.json` are unmodified copies downloaded from the canonical URLs recorded in `sources.json`. The accompanying SHA-256 values identify the actual downloaded bytes, not a claim of scientific validation.

Upstream: [agentplugins/agent-plugins-spec](https://github.com/agentplugins/agent-plugins-spec). Schemas are software material licensed under Apache-2.0; its complete license is included as `Apache-2.0.txt`, following [upstream licensing](https://github.com/agentplugins/agent-plugins-spec/blob/main/LICENSE.md). These upstream terms are separate from the licensing decision for Parrhesia itself.

The optional `jsonschema` development check validates both root configuration documents offline against these snapshots. Runtime MCP service startup neither imports `jsonschema` nor fetches schemas. Semantic checks, host discovery, and live model behavior are separate verification layers.
