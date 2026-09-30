# conversation-modes Specification

## Purpose
Keeps each conversation inside one data domain and bounds how much context the LLM receives, so answers stay on topic and token use stays predictable.

## Requirements

### Requirement: A conversation exposes core tools plus its mode's tools
The MCP server SHALL register all 19 tools. The orchestrator SHALL expose to the LLM only the 11 core tools plus the tools of the conversation's mode: 5 Revive tools in `revive` mode, 3 exchange tools in `exchange` mode. With no mode, all tools SHALL be exposed.

#### Scenario: Revive mode
- **WHEN** a conversation runs in `revive` mode
- **THEN** the LLM is offered 16 tools and none of the exchange-only tools

#### Scenario: Exchange mode
- **WHEN** a conversation runs in `exchange` mode
- **THEN** the LLM is offered 14 tools and none of the Revive-only tools

### Requirement: Switching mode starts a fresh thread
When a saved chat receives a message in a different mode from the one it was saved with, the API SHALL clear that chat's messages and tool calls before answering, so context from one domain never reaches the other.

#### Scenario: Mode switch
- **WHEN** a chat saved in `exchange` mode receives a `revive` message
- **THEN** the question is answered with no prior history

### Requirement: Context stays bounded
Each tool result passed to the LLM SHALL be truncated to at most 3000 characters, with a note telling the model to narrow the request. History carried between turns SHALL contain only questions and final answers, not tool traces, and at most the last 10 turns. A turn SHALL make at most 8 tool-use iterations.

#### Scenario: Large tool result
- **WHEN** a tool returns more than 3000 characters
- **THEN** the LLM receives a truncated result marked TRUNCATED that suggests narrowing the request

#### Scenario: Small tool result
- **WHEN** a tool returns a small result
- **THEN** the LLM receives it unchanged
