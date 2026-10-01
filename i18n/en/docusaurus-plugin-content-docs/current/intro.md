---
sidebar_position: 1
slug: /
---

# fab.engineering

**Place your company's AI agents on the org chart, manage them, and audit them.**

fab.engineering is an open-source platform that runs on your own server. Every agent has a name, a role, a department and a responsible human; agents sit in the company structure like any other employee. Policies, approval flows and an audit trail come built in.

## Who is it for, and where to start

| Who you are | Start here |
|---|---|
| **Company executive / founder**: I want to know what it does and how to set it up | [First Steps](/getting-started/first-steps) → [AI Setup](/guide/onboarding) |
| **Department employee**: I will work with an agent | [Chatting with an Agent](/guide/chat), [Task Requests and Inbox](/guide/tasks-and-inbox) |
| **Department manager**: I manage my team's agents and approvals | [Agents](/guide/agents), [Change Requests](/guide/change-requests) |
| **IT / installer** | [Requirements](/getting-started/requirements), [Installation](/getting-started/installation), [Settings](/guide/settings) |
| **Developer**: I will work with opencode on my own machine | [Developer Workstation](/workstation/overview) |
| **Department employee who wants to work in a terminal** | [The fab terminal client](/fab/overview) |
| **Building or reviewing the platform** | [Technical](/technical/architecture), [Developer Notes](/developer-notes/overview) |

## Three ways to work

Same server, same policies, same audit trail; three doors depending on the job:

| Surface | For | Status |
|---|---|---|
| **Web interface** | Everyone: chat, flows, approvals, administration | Ready to use |
| **Developer workstation** (`3pa` + opencode) | Software developers | Ready to use |
| **`fab` terminal client** | Departments such as finance, accounting, sales | In development: there is no real workspace runtime yet, see [fab](/fab/overview) |

## Core concepts

| Concept | Meaning |
|---|---|
| **Company** | The top-level unit. One installation can manage several companies; their data is kept separate. |
| **Department** | A unit of the company. It can belong to a parent department and has goals and policies. |
| **Personnel** | A person on the org chart. The type is either **human** or **agent**. |
| **Agent** | An AI model (e.g. Claude, GPT, Gemini) bound to a personnel record with its skills and policies. Every agent has a responsible human. |
| **Skill** | A tool the agent can use: web search, chart generation, a database query, an external API, and so on. |
| **Policy** | A written rule that applies to a company, a department or an agent. |
| **Platform user** | A person who signs in with an email and password. Added by invitation; the role decides what they can see. |

## Principles

- **On your own server.** Your data stays with you; AI providers are reached only with the keys you define.
- **Model independent.** Anthropic, OpenAI, Google, Mistral, Qwen, local models (Ollama, LM Studio) and any OpenAI-compatible address can be used.
- **Human approval.** Agent configuration changes go through two-stage approval; handing a task from one agent to another needs human approval.
- **Traceability.** Important actions are written to an audit log. In the developer workstation layer the log is additionally a tamper-evident hash chain.
- **Open source.** Source code is on [GitHub](https://github.com/fab-agent/agentic-organization); see the `LICENSE` file in the repository for the license.

## Try it

There is a live demo environment: [demo.agent.fab.engineering](https://demo.agent.fab.engineering) (a one-time code is sent to your email). To install on your own server, go to [Installation](/getting-started/installation).

## Contact

[LinkedIn](https://www.linkedin.com/in/kuntaykunt/) · [X](https://x.com/kuntaykunt) · bilgi@kuntaykunt.com
