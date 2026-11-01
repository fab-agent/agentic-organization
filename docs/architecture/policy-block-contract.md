# Policy block contract

What the policy engine executes from a Policy's markdown body, and what it refuses
(ADR-0005, ADR-0026). Code: `backend/services/policy_engine.py`
(`parse_policy_content`, `validate_policy_content`).

## Executable blocks

Fences with the info string `policy`, `json` or `yaml` (case-insensitive) are
executed. Each must be **closed** and must **parse** (JSON first, then YAML). A
block that parses to a list yields its rule objects; a `policy` block must be a
list (an empty block is fine). Parsed `json`/`yaml` data that is not rule-shaped is
not a rule block (see "Not executed"). A rule has `match` (an object) and `effect`
(`allow`, `ask`, `deny`); `match` may have `tool`, `provenance`, `source`, `args`,
`command`.

Anything else in an executable fence is a *problem*, not a skipped block:

| Problem | Example |
|---|---|
| unterminated block | opening fence, no closing fence |
| unparseable block | invalid JSON and invalid YAML |
| not a list (`policy` fence) | a single rule object |
| rule object outside a list | `json`/`yaml` fence with `match`/`effect` at the root |
| non-object rule | `["x"]` |
| bad rule shape | unknown `effect`, `match` not an object, a pattern that is not a string or list |
| too large | document > 1 MiB, block > 64 KiB, more than 500 rules |

At **save time** (`POST/PUT /policies`, change-request `content`) a policy with
problems is refused with `422 malformed_policy`. At **runtime** a stored policy with
problems makes every decision for the personas it applies to a fail-closed deny, in
every mode except `off` (which skips the engine on purpose), until it is fixed. It
never silently loses rules. A leading byte-order mark is ignored; any other U+FEFF is
data and is never removed. Problem texts name the kind and rule position (`rule #2`),
never ids, effects or other policy text.

## Not executed

Put prose and examples in a fence with any other info string, usually ` ```text `.
Parsed JSON/YAML that is not rule-shaped (a prose object, a scalar, an empty block)
adds no rules and no problem. There is no guessing whether an unparseable block
"looks like a rule": unparseable means problem.

## Fence grammar

Backtick fences only: an opener is a line of three or more backticks (at most three
spaces of indent) with an info string that has no backticks; the closer is a line of
at least as many backticks and nothing else. Backticks inside a line, for example in
a JSON string, never close a block. A block opened with a non-executable info
string, including a longer outer fence, hides what it contains. Tilde fences and
fences inside lists or quotes are not recognised, and this is not full CommonMark.

## Rollout

Before enabling the gate on an existing installation, list stored policies that
would fail closed:

    cd backend && python scripts/policy_inventory.py

It only reads (SELECT; for production use a read-only database role) and prints policy ids, names and problem kinds with rule positions, never policy text. Fix a listed
policy by repairing its block or moving prose to a ` ```text ` fence.
