---
sidebar_position: 5
---

# Assistant (the simple view for departments)

A small screen for departments such as accounting, finance and HR. You do not need to see the company's whole structure, skills or policies; you only talk to your own assistant, send files, and see the context that is yours.

**Who sees it:** people whose only role is **Assistant user** (`assistant_user`). With a management role as well, the normal interface opens. A department head, executive or founder grants the role ([People and Access](/guide/people-and-access)).

## What you can do

- **Chat and files:** write to your own assistant; attach a PDF, text or image. Answers are shown as Markdown.
- **Status line:** while the assistant works you see short states such as "Working: tool name". Raw reasoning, tool arguments and tool results are not sent to this view.
- **Sources:** when an answer used knowledge from past work, a "Sources" fold appears under it: kind, date and a short snippet with personal identifiers removed. Full text and internal ids are not shown.
- **My outputs:** the files in the assistant's workspace `out/` are listed and can be saved. A file is never opened automatically; types that can carry macros or commands ask for confirmation first. (The workspace runtime is not real yet, so the list may be empty for now.)
- **My context:** your name, department, manager and colleagues (name and role only), the tools connected to your assistant, the policies that apply to you, the company's mission and vision, department goals.

## What you cannot do

- See company-wide lists (people, departments, policies, skills, dashboard).
- Edit agents, skills or policies; that needs a management role.
- See other people's chats with an agent, memory summaries or delegation results.
- Obtain developer (terminal) credentials or touch installation-wide settings (provider keys, database connections, backup).

Not there yet: the "My review" screen and the local **Assistant** folder helper; see [Known limits](/developer-notes/known-limits).
