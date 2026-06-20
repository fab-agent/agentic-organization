---
id: department-hierarchy
title: Department Hierarchy
sidebar_label: Department Hierarchy
---

# Department Hierarchy

fab.engineering lets you model your company's internal units in a hierarchical structure. Each department can be linked to a parent department, turning your company structure into a real tree rather than a flat list.

---

## Core Concepts

| Concept | Description |
|---|---|
| **Root Department** | The top-level department with no parent unit |
| **Sub-unit** | A department linked to a root or another sub-department |
| `parent_id` | The database ID of the sub-unit's parent department |

---

## Creating a Department

Go to the **Departments** page and click the **New Department** button. Fill in the following fields in the form that slides in from the right:

1. **Department Name** — Required. Example: `Software Development`
2. **Slug** — A URL-friendly short name. Non-ASCII characters are converted automatically; can be edited manually.
3. **Parent Department** — Select a parent unit here if you want to create a hierarchy. Leave blank to make it a root unit.
4. **Description** — Free text briefly describing the department's responsibilities.
5. **Department Goals / OKRs** — Each line counts as a separate goal. Free text.
6. **Department Policies** — The list of rules that all agents linked to this department must follow. Add each policy separately.
7. **Status** — `Active` or `Inactive`.

The department is created and added to the table when you click **Save**.

:::info Automatic Slug Generation
The slug field is auto-populated as you type the department name. You can override it manually at any time. The slug is used as the directory name when the organization structure is written to Git repositories.
:::

---

## Hierarchy Rules

- A department can be linked to **only one** parent department at a time.
- A department cannot select itself as its parent unit.
- To prevent circular dependencies, the form excludes departments that are already a sub-unit from the parent unit list.
- When a department is deleted, the `parent_id` link of its sub-units is removed (sub-units become root units; they are not deleted).

---

## Department List

The Departments page is summarized with three count cards:

| Card | Description |
|---|---|
| **Total** | All departments in the company |
| **Active** | Departments with `Active` status |
| **Sub-unit** | Units with a populated `parent_id`, i.e. linked to another department |

In the table, the **Parent Unit** column for each department shows the unit it belongs to, if any. Sub-unit rows use the ↳ symbol and purple color; root units are shown in blue.

---

## Org Chart — Department View

The **Organization** page offers two different views:

| View | Description |
|---|---|
| **Personnel Tree** | A hierarchical tree showing each personnel member and their agent |
| **Department** | A compact view listing departments by hierarchy and showing the human/agent count for each unit |

In the department view, root units can be collapsed/expanded; the number of humans and agents working in each unit is displayed beside it. Sub-units are listed with indentation.

---

## Departments and Policies

Policies added to a department form the default guardrail list for all agents linked to that department. These policies are automatically pre-selected during agent configuration.

For details on policy management → [Policy & Skills](./policy-and-skills.md)

---

## API Endpoints

| Endpoint | Method | Description | Permission |
|---|---|---|---|
| `/departments` | POST | Create a new department | `dept_head+` |
| `/departments?company_id=` | GET | All departments for a company | `dept_head+` |
| `/departments/{id}` | PUT | Update a department | `dept_head+` |
| `/departments/{id}` | DELETE | Delete a department | `dept_head+` |
| `/departments/tree?company_id=` | GET | Hierarchical tree (parent→children) | `dept_head+` |
