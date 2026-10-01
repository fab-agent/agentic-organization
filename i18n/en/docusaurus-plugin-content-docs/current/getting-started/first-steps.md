---
sidebar_position: 3
---

# First Steps

After installation, follow this order to get a company up and running. Each step links to the relevant guide page.

## 1. Sign in

Sign in with the account you created in the [setup wizard](/getting-started/installation#first-launch). This account has the **founder** role and can access everything.

## 2. Add an AI provider

Under **Settings → AI Providers**, enter the key of at least one provider and press **Save & Test**. The key is stored encrypted. Without this step agents cannot reply. Details: [Settings](/guide/settings#ai-providers).

## 3. Set up the organization

There are two ways:

- **Quick way:** **Settings → Set Up with AI**. The system researches your company on the web, asks you 3 to 5 questions, and proposes departments, people, agents, skills and policies in one go. You approve the preview. → [AI Setup](/guide/onboarding)
- **By hand:** Add departments, people and agents one by one. → [Organization](/guide/organization), [Agents](/guide/agents)

## 4. Invite the team

On the **Structure → People** page, add a person's email, send an invitation and pick a role. The person signs in with a temporary password and sets a new one at first login. → [People and Access](/guide/people-and-access)

## 5. Talk to an agent

On the **Jobs** page, pick an agent and start a new chat. → [Chatting with an Agent](/guide/chat)

## 6. Automate the work

For a recurring task, set up a timed flow on the **Flows** page; the result lands in the relevant person's Inbox. → [Autonomous Flows](/guide/flows), [Task Requests and Inbox](/guide/tasks-and-inbox)

## Interface map

The sections shown in the left sidebar depend on the person's role:

| Section | Address | Who sees it |
|---|---|---|
| **Dashboard** | `/` | Everyone |
| **Structure** (Departments · People · Agents · Skills · Policies) | `/departments` and its siblings | Department head and above |
| **Organization** | `/org-chart` | Department head and above |
| **Changes** | `/change-requests` | Department head and above |
| **Flows** | `/flows` | Agent owner and above |
| **Jobs** (chat) | `/chat` | Everyone |
| **Delegation** | `/a2a` | Everyone |
| **Settings** | `/settings` | Executive and above |

The **Inbox** (`/inbox`) has no link in the sidebar. People with the `User` role are taken straight to it at sign-in; others open the address in the browser. The **Agents** page opens at sign-in for the `Agent owner` role and is also reachable from the Structure tabs.

:::info How are roles applied in the interface?
The visibility above is the interface showing menus according to role. On the server (API) side, company membership is required for all operations; some also require a role (company settings, user management, provider keys, and so on). Details: [People and Access → Roles](/guide/people-and-access#roles) and [Security](/technical/security).
:::

## Language and theme

Pick **Türkçe** or **English** from the selector at the top right. There are no other languages.
