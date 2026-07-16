"""
Agent runtime — system prompt builder, tool definitions, multi-provider streaming.

Supported providers (routed by model name prefix):
  gemini-*   → Google Gemini via google-genai SDK
  claude-*   → Anthropic Claude
  gpt-*      → OpenAI GPT
"""

import asyncio
import json
from collections.abc import AsyncGenerator

from sqlmodel import select

from core.security import decrypt
from database import get_session
from models import (
    AgentConfig,
    AgentPolicyLink,
    AgentSession,
    Department,
    DepartmentPolicyLink,
    Personnel,
    Policy,
    ProviderKey,
    SessionMessage,
    Skill,
)
from services.mcp_client import call_http_tool, call_mcp_sse_tool, execute_builtin
from services.memory_service import load_agent_memories

# ── Attachment helpers ────────────────────────────────────────────────────────


def _build_message_with_attachments(
    user_message: str, attachments: list[dict] | None
) -> str:
    """Prepend file attachment content to the user message for the LLM."""
    if not attachments:
        return user_message
    parts = []
    for att in attachments:
        att_type = att.get("type", "")
        filename = att.get("filename", "dosya")
        content = att.get("content", "")
        if att_type == "pdf":
            parts.append(f"[Yüklenen PDF: {filename}]\n{content}")
        elif att_type == "image":
            # Keep a short note; vision-capable providers can parse the data URI
            # from the attachment payload handled in the provider layer.
            parts.append(f"[Yüklenen görsel: {filename}] — Görsel içerik mevcuttur.")
        elif att_type == "text":
            parts.append(f"[Yüklenen metin dosyası: {filename}]\n{content}")
    if not parts:
        return user_message
    return "\n\n".join(parts) + "\n\n---\n\n" + user_message


# ── System prompt builder ─────────────────────────────────────────────────────


def build_system_prompt(
    person: Personnel,
    dept: Department | None,
    skills: list[Skill],
    policy_names: list[str] | None = None,
    rag_query: str | None = None,
    company_id: str | None = None,
) -> str:
    lines = [
        f"You are {person.name}.",
    ]
    if person.title:
        lines.append(f"Title: {person.title}")
    if person.role:
        lines.append(f"Role: {person.role}")
    if dept:
        lines.append(f"Department: {dept.name}")
        if dept.goals:
            lines.append(f"\nDepartment Goals:\n{dept.goals}")
    if policy_names:
        lines.append("\nPolicies you must follow:")
        for p in policy_names:
            lines.append(f"  - {p}")

    if skills:
        active_skills = [s for s in skills if s.is_active]
        if active_skills:
            lines.append(
                "\nAvailable tools/skills: " + ", ".join(s.name for s in active_skills)
            )

    # Inject agent memory from past sessions
    try:
        memories = load_agent_memories(person.id, limit=3)
        if memories:
            lines.append("\nContext from your previous sessions:")
            for mem in memories:
                lines.append(f"  - {mem}")
    except Exception:
        pass  # Never block session start due to memory failure

    # Inject RAG context — semantically relevant past task results and session summaries
    if rag_query:
        try:
            from services.rag_service import search as rag_search

            hits = rag_search(
                rag_query, company_id=company_id, personnel_id=person.id, k=4
            )
            if hits:
                lines.append("\n--- Relevant knowledge from past work ---")
                for hit in hits:
                    date = hit["created_at"][:10]
                    source = hit["source_type"].replace("_", " ")
                    snippet = hit["chunk_text"][:300].replace("\n", " ")
                    lines.append(f"[{date}] ({source}) {snippet}")
                lines.append("--- End of relevant knowledge ---")
        except Exception:
            pass  # Never block session start due to RAG failure

    lines.append("\nRespond helpfully and concisely. Use tools when they would help.")
    return "\n".join(lines)


# ── Tool definition builder ───────────────────────────────────────────────────

_BUILTIN_SCHEMAS: dict[str, dict] = {
    "web_search": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query"}},
        "required": ["query"],
    },
    "text_to_chart": {
        "type": "object",
        "properties": {
            "data": {"type": "string", "description": "Data as JSON or CSV string"},
            "chart_type": {"type": "string", "description": "bar, line, pie, etc."},
            "title": {"type": "string"},
        },
        "required": ["data"],
    },
    "code_execution": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "language": {"type": "string", "description": "Programming language"},
        },
        "required": ["code"],
    },
    "delegate_to_agent": {
        "type": "object",
        "properties": {
            "to_agent_slug": {
                "type": "string",
                "description": "Slug of the target agent personnel",
            },
            "task": {
                "type": "string",
                "description": "Task description for the target agent",
            },
            "context": {
                "type": "string",
                "description": "Additional context or data to pass",
            },
        },
        "required": ["to_agent_slug", "task"],
    },
    "journal_write": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Journal entry text (markdown supported)",
            },
            "title": {
                "type": "string",
                "description": "Optional short title for the entry",
            },
        },
        "required": ["content"],
    },
    "db_query": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "SELECT SQL query to execute"},
        },
        "required": ["sql"],
    },
    "function": {
        "type": "object",
        "properties": {
            "params": {
                "type": "string",
                "description": "JSON string of parameters to pass to the function",
            },
        },
        "required": [],
    },
    "instagram_post": {
        "type": "object",
        "properties": {
            "image_url": {
                "type": "string",
                "description": "Public HTTPS URL of the image to post",
            },
            "caption": {
                "type": "string",
                "description": "Post caption (hashtags allowed)",
            },
        },
        "required": ["image_url", "caption"],
    },
    "whatsapp_send": {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Text message to send"},
            "to": {
                "type": "string",
                "description": "Recipient phone number in E.164 format (optional — uses default if omitted)",
            },
        },
        "required": ["message"],
    },
}


def build_tool_definitions(skills: list[Skill]) -> list[dict]:
    """Return Gemini-compatible function declarations for active skills."""
    tools = []
    for s in skills:
        if not s.is_active:
            continue

        cfg = json.loads(s.config_json) if s.config_json else {}
        parameters: dict = {"type": "object", "properties": {}, "required": []}

        if s.skill_type == "builtin":
            fn_name = cfg.get("function_name", s.name)
            parameters = _BUILTIN_SCHEMAS.get(fn_name, parameters)
        elif s.skill_type in ("mcp", "http"):
            input_schema = cfg.get("input_schema") or {}
            if input_schema:
                parameters = input_schema
            else:
                parameters = {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string", "description": "Tool input"}
                    },
                    "required": ["input"],
                }
        elif s.skill_type == "function":
            parameters = _BUILTIN_SCHEMAS.get("function", parameters)

        elif s.skill_type == "database":
            # Inject schema context into tool description so LLM knows the DB structure
            parameters = _BUILTIN_SCHEMAS.get("db_query", parameters)

        description = s.description or s.name
        if s.skill_type == "database":
            db_id = cfg.get("db_id", "")
            if db_id:
                try:
                    from models import DatabaseConnection
                    from services.database_service import build_schema_context

                    with get_session() as _db:
                        db_row = _db.get(DatabaseConnection, db_id)
                    if db_row and db_row.schema_json:
                        ctx = build_schema_context(
                            db_row.schema_json, db_row.examples_json
                        )
                        description = f"{description}\n\n{ctx}"
                except Exception:
                    pass

        tools.append(
            {
                "name": s.name.replace(" ", "_").lower(),
                "description": description,
                "parameters": parameters,
                "_skill_id": s.id,
                "_skill_type": s.skill_type,
                "_config": cfg,
            }
        )
    return tools


# ── Tool executor ─────────────────────────────────────────────────────────────


async def execute_skill(
    tool_name: str,
    args: dict,
    skills: list[Skill],
    session_id: str | None = None,
    agent_id: str | None = None,
) -> str:
    """Find the matching skill and execute it."""
    normalized = tool_name.replace(" ", "_").lower()
    skill = next(
        (s for s in skills if s.name.replace(" ", "_").lower() == normalized), None
    )

    if not skill:
        return f"[Tool '{tool_name}' not found]"

    cfg = json.loads(skill.config_json) if skill.config_json else {}

    try:
        if skill.skill_type == "builtin":
            fn_name = cfg.get("function_name", skill.name)
            result = await execute_builtin(
                fn_name, args, session_id=session_id, agent_id=agent_id
            )
            return str(result)

        elif skill.skill_type == "mcp":
            result = await call_mcp_sse_tool(
                url=cfg.get("url", ""),
                auth_type=cfg.get("auth_type", "none"),
                auth_value=cfg.get("auth_value"),
                tool_name=skill.name,
                args=args,
            )
            return str(result)

        elif skill.skill_type == "http":
            headers = cfg.get("headers", {})
            result = await call_http_tool(
                url=cfg.get("url", ""),
                method=cfg.get("method", "POST"),
                headers=headers,
                args=args,
            )
            return str(result)

        elif skill.skill_type == "function":
            # Inject the stored code into args so the builtin handler can run it
            code = cfg.get("code", "")
            result = await execute_builtin(
                "function",
                {**args, "__code__": code},
                session_id=session_id,
                agent_id=agent_id,
            )
            return str(result)

        elif skill.skill_type == "database":
            # db_id stored in config; inject it so the builtin knows which DB to query
            db_id = cfg.get("db_id", "")
            result = await execute_builtin(
                "db_query",
                {**args, "db_id": db_id},
                session_id=session_id,
                agent_id=agent_id,
            )
            return str(result)

    except Exception as e:
        return f"[Tool error: {e}]"

    return f"[Unhandled skill type: {skill.skill_type}]"


# ── Provider key retrieval ────────────────────────────────────────────────────


def get_decrypted_key(provider: str) -> str | None:
    with get_session() as session:
        row = session.exec(
            select(ProviderKey).where(
                ProviderKey.provider == provider,
                ProviderKey.status == "active",
            )
        ).first()
        if not row:
            return None
        return decrypt(row.encrypted_key)


def detect_provider(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("gemini"):
        return "google"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3"):
        return "openai"
    if m.startswith("qwen"):
        return "qwen"
    if m.startswith("dall-e"):
        return "openai"
    if m.startswith(("wanx", "flux", "stable-diffusion")):
        return "qwen"
    return "google"


def is_image_gen_model(model: str) -> bool:
    """Check model type from the capabilities cache; fall back to prefix detection."""
    from services.provider_service import _infer_model_type, load_model_capabilities

    caps = load_model_capabilities()
    if model in caps:
        return caps[model] == "image"
    return _infer_model_type(model) == "image"


# ── Gemini streaming ──────────────────────────────────────────────────────────


def _gemini_history(messages: list[SessionMessage]) -> list[dict]:
    """Convert stored messages to Gemini contents format."""
    history = []
    for msg in messages:
        role = "user" if msg.role == "user" else "model"
        parts = [{"text": msg.content}]

        if msg.tool_calls_json and role == "model":
            tool_calls = json.loads(msg.tool_calls_json)
            for tc in tool_calls:
                parts.append(
                    {"function_call": {"name": tc["name"], "args": tc["args"]}}
                )

        if msg.tool_results_json and role == "user":
            # tool results are attached to the following user message as function_response
            tool_results = json.loads(msg.tool_results_json)
            for tr in tool_results:
                parts.append(
                    {
                        "function_response": {
                            "name": tr["name"],
                            "response": {"result": tr["result"]},
                        }
                    }
                )

        history.append({"role": role, "parts": parts})
    return history


async def _stream_gemini(
    model_name: str,
    api_key: str,
    system_prompt: str,
    history: list[dict],
    user_message: str,
    tool_defs: list[dict],
    skills: list[Skill],
    session_id: str | None = None,
    agent_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    # Strip internal metadata from tool defs before sending to Gemini
    gemini_tools = []
    if tool_defs:
        func_decls = []
        for td in tool_defs:
            func_decls.append(
                types.FunctionDeclaration(
                    name=td["name"],
                    description=td["description"],
                    parameters=types.Schema(**_schema_from_dict(td["parameters"])),
                )
            )
        gemini_tools = [types.Tool(function_declarations=func_decls)]

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=gemini_tools if gemini_tools else None,
    )

    contents = history + [{"role": "user", "parts": [{"text": user_message}]}]

    all_tool_calls: list[dict] = []
    all_tool_results: list[dict] = []

    max_loops = 8
    for _ in range(max_loops):
        text_parts: list[str] = []
        loop_tool_calls: list[dict] = []

        def _sync_call():
            nonlocal text_parts, loop_tool_calls
            resp = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            for part in resp.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    text_parts.append(part.text)
                elif hasattr(part, "function_call") and part.function_call:
                    loop_tool_calls.append(
                        {
                            "name": part.function_call.name,
                            "args": dict(part.function_call.args),
                        }
                    )

        await asyncio.to_thread(_sync_call)

        if text_parts:
            yield {"type": "text", "content": "".join(text_parts)}

        if not loop_tool_calls:
            break

        all_tool_calls.extend(loop_tool_calls)

        # Execute tools
        tool_response_parts = []
        for tc in loop_tool_calls:
            yield {"type": "tool_call", "name": tc["name"], "args": tc["args"]}
            result = await execute_skill(
                tc["name"], tc["args"], skills, session_id=session_id, agent_id=agent_id
            )
            yield {"type": "tool_result", "name": tc["name"], "result": result}
            all_tool_results.append({"name": tc["name"], "result": result})
            tool_response_parts.append(
                {
                    "function_response": {
                        "name": tc["name"],
                        "response": {"result": result},
                    }
                }
            )

        # Add model response and tool results to contents for next loop
        model_parts = []
        for tc in loop_tool_calls:
            model_parts.append(
                {"function_call": {"name": tc["name"], "args": tc["args"]}}
            )
        contents.append({"role": "model", "parts": model_parts})
        contents.append({"role": "user", "parts": tool_response_parts})

    yield {
        "type": "_meta",
        "tool_calls": all_tool_calls,
        "tool_results": all_tool_results,
    }


def _schema_from_dict(d: dict) -> dict:
    """Convert a plain dict schema to keyword args for types.Schema."""
    from google.genai import types

    result: dict = {}

    type_map = {
        "object": "OBJECT",
        "string": "STRING",
        "number": "NUMBER",
        "integer": "INTEGER",
        "boolean": "BOOLEAN",
        "array": "ARRAY",
    }

    raw_type = d.get("type", "object")
    result["type"] = type_map.get(raw_type.lower(), "OBJECT")

    if "description" in d:
        result["description"] = d["description"]

    if "properties" in d:
        result["properties"] = {
            k: types.Schema(**_schema_from_dict(v)) for k, v in d["properties"].items()
        }

    if "required" in d:
        result["required"] = d["required"]

    if "items" in d:
        result["items"] = types.Schema(**_schema_from_dict(d["items"]))

    return result


# ── Anthropic streaming ───────────────────────────────────────────────────────


async def _stream_anthropic(
    model_name: str,
    api_key: str,
    system_prompt: str,
    history: list[SessionMessage],
    user_message: str,
    tool_defs: list[dict],
    skills: list[Skill],
    session_id: str | None = None,
    agent_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    messages = []
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message})

    ant_tools = [
        {
            "name": td["name"],
            "description": td["description"],
            "input_schema": td["parameters"],
        }
        for td in tool_defs
    ]

    all_tool_calls: list[dict] = []
    all_tool_results: list[dict] = []
    total_tokens_anthropic = 0

    max_loops = 8
    for _ in range(max_loops):
        response_text = ""
        loop_tool_calls: list[dict] = []
        loop_tok = [0]

        def _sync_call():
            nonlocal response_text, loop_tool_calls
            resp = client.messages.create(
                model=model_name,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
                tools=ant_tools if ant_tools else [],
            )
            if resp.usage:
                loop_tok[0] = (resp.usage.input_tokens or 0) + (
                    resp.usage.output_tokens or 0
                )
            for block in resp.content:
                if block.type == "text":
                    response_text = block.text
                elif block.type == "tool_use":
                    loop_tool_calls.append(
                        {"id": block.id, "name": block.name, "args": block.input}
                    )

        await asyncio.to_thread(_sync_call)
        total_tokens_anthropic += loop_tok[0]

        if response_text:
            yield {"type": "text", "content": response_text}

        if not loop_tool_calls:
            break

        all_tool_calls.extend(loop_tool_calls)
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["args"],
                    }
                    for tc in loop_tool_calls
                ],
            }
        )

        tool_result_blocks = []
        for tc in loop_tool_calls:
            yield {"type": "tool_call", "name": tc["name"], "args": tc["args"]}
            result = await execute_skill(
                tc["name"], tc["args"], skills, session_id=session_id, agent_id=agent_id
            )
            yield {"type": "tool_result", "name": tc["name"], "result": result}
            all_tool_results.append({"name": tc["name"], "result": result})
            tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result,
                }
            )

        messages.append({"role": "user", "content": tool_result_blocks})

    yield {
        "type": "_meta",
        "tool_calls": all_tool_calls,
        "tool_results": all_tool_results,
        "tokens_used": total_tokens_anthropic,
    }


# ── Image generation (Qwen wanx/qwen-image via DashScope task API, OpenAI dall-e) ────────


def _qwen_task_base(stored_base_url: str | None) -> str:
    """Derive the DashScope root from the stored compatible-mode base_url."""
    if stored_base_url:
        # e.g. https://dashscope-intl.aliyuncs.com/compatible-mode/v1 → https://dashscope-intl.aliyuncs.com
        return stored_base_url.split("/compatible-mode")[0]
    return "https://dashscope-intl.aliyuncs.com"


async def _generate_image_qwen(
    api_key: str,
    model_name: str,
    prompt: str,
    stored_base_url: str | None = None,
) -> AsyncGenerator[dict, None]:
    """DashScope async task API for qwen-image-* and wanx-* models."""
    import time

    import httpx

    task_root = _qwen_task_base(stored_base_url)
    submit_url = f"{task_root}/api/v1/services/aigc/text2image/image-synthesis"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    body = {
        "model": model_name,
        "input": {"prompt": prompt},
        "parameters": {"size": "1024*1024", "n": 1},
    }

    def _submit():
        with httpx.Client(timeout=20) as c:
            r = c.post(submit_url, json=body, headers=headers)
            r.raise_for_status()
            return r.json()

    def _poll(task_id: str):
        poll_url = f"{task_root}/api/v1/tasks/{task_id}"
        poll_headers = {"Authorization": f"Bearer {api_key}"}
        for _ in range(30):  # max ~90 seconds
            time.sleep(3)
            with httpx.Client(timeout=15) as c:
                r = c.get(poll_url, headers=poll_headers)
                r.raise_for_status()
                data = r.json()
            status = data.get("output", {}).get("task_status", "")
            if status == "SUCCEEDED":
                return data.get("output", {}).get("results", [])
            if status == "FAILED":
                raise RuntimeError(
                    data.get("output", {}).get("message", "Görev başarısız oldu")
                )
        raise RuntimeError("Resim üretme zaman aşımına uğradı (90s)")

    try:
        submit_data = await asyncio.to_thread(_submit)
    except Exception as e:
        yield {"type": "error", "message": f"Resim görevi başlatılamadı: {e}"}
        yield {"type": "_meta", "tool_calls": [], "tool_results": []}
        return

    task_id = submit_data.get("output", {}).get("task_id")
    if not task_id:
        yield {"type": "error", "message": "DashScope task_id alınamadı"}
        yield {"type": "_meta", "tool_calls": [], "tool_results": []}
        return

    yield {"type": "text", "content": "_Resim üretiliyor…_"}

    try:
        results = await asyncio.to_thread(_poll, task_id)
    except Exception as e:
        yield {"type": "error", "message": f"Resim üretilemedi: {e}"}
        yield {"type": "_meta", "tool_calls": [], "tool_results": []}
        return

    parts = []
    for img in results:
        img_url = img.get("url")
        if img_url:
            parts.append(f"![Üretilen resim]({img_url})")
        revised = img.get("actual_prompt", "")
        if revised and revised != prompt:
            parts.append(
                f"\n<details><summary>Genişletilmiş prompt</summary>{revised}</details>"
            )

    if not parts:
        yield {"type": "error", "message": "Resim üretilemedi: sonuç boş döndü"}
    else:
        yield {"type": "text", "content": "\n".join(parts)}
    yield {"type": "_meta", "tool_calls": [], "tool_results": []}


async def _generate_image_openai(
    api_key: str,
    model_name: str,
    prompt: str,
    size: str = "1024x1024",
) -> AsyncGenerator[dict, None]:
    """OpenAI /images/generations for dall-e-* models."""
    import httpx

    url = "https://api.openai.com/v1/images/generations"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": model_name, "prompt": prompt, "n": 1, "size": size}

    def _sync_call():
        with httpx.Client(timeout=120) as c:
            r = c.post(url, json=body, headers=headers)
            r.raise_for_status()
            return r.json()

    try:
        data = await asyncio.to_thread(_sync_call)
    except Exception as e:
        yield {"type": "error", "message": f"Resim üretilemedi: {e}"}
        yield {"type": "_meta", "tool_calls": [], "tool_results": []}
        return

    parts = []
    for img in data.get("data", []):
        img_url = img.get("url")
        b64 = img.get("b64_json")
        if img_url:
            parts.append(f"![Üretilen resim]({img_url})")
        elif b64:
            parts.append(f"![Üretilen resim](data:image/png;base64,{b64})")
        revised = img.get("revised_prompt", "")
        if revised and revised != prompt:
            parts.append(f"\n*Revize prompt: {revised}*")

    yield {"type": "text", "content": "\n".join(parts) or "Resim üretilemedi"}
    yield {"type": "_meta", "tool_calls": [], "tool_results": []}


async def _generate_image(
    provider: str,
    model_name: str,
    api_key: str,
    prompt: str,
) -> AsyncGenerator[dict, None]:
    if provider == "qwen":
        stored_base_url = None
        from sqlmodel import select as _sel

        from database import get_session as _gs
        from models import ProviderKey as _PK

        with _gs() as _db:
            _row = _db.exec(_sel(_PK).where(_PK.provider == "qwen")).first()
            if _row:
                stored_base_url = _row.base_url
        async for ev in _generate_image_qwen(
            api_key, model_name, prompt, stored_base_url
        ):
            yield ev
    else:
        async for ev in _generate_image_openai(api_key, model_name, prompt):
            yield ev


# ── OpenAI-compatible streaming (OpenAI + Qwen) ───────────────────────────────

_OPENAI_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
}


async def _stream_openai_compatible(
    provider: str,
    model_name: str,
    api_key: str,
    system_prompt: str,
    history: list[SessionMessage],
    user_message: str,
    tool_defs: list[dict],
    skills: list[Skill],
    session_id: str | None = None,
    agent_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    from openai import OpenAI

    base_url = _OPENAI_BASE_URLS.get(provider, "https://api.openai.com/v1")
    if provider == "qwen":
        from sqlmodel import select as _sel

        from database import get_session as _gs
        from models import ProviderKey as _PK

        with _gs() as _db:
            _row = _db.exec(_sel(_PK).where(_PK.provider == "qwen")).first()
            if _row and _row.base_url:
                base_url = _row.base_url
    client = OpenAI(api_key=api_key, base_url=base_url)

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message})

    oai_tools = [
        {
            "type": "function",
            "function": {
                "name": td["name"],
                "description": td["description"],
                "parameters": td["parameters"],
            },
        }
        for td in tool_defs
    ]

    all_tool_calls: list[dict] = []
    all_tool_results: list[dict] = []
    accumulated_tokens = 0

    max_loops = 8
    for _ in range(max_loops):
        response_text = ""
        loop_tool_calls: list[dict] = []
        loop_tokens = [0]  # list so inner func can mutate

        def _sync_call():
            nonlocal response_text, loop_tool_calls
            kwargs: dict = {
                "model": model_name,
                "messages": messages,
                "max_tokens": 4096,
            }
            if oai_tools:
                kwargs["tools"] = oai_tools
            resp = client.chat.completions.create(**kwargs)
            if resp.usage:
                t = getattr(resp.usage, "total_tokens", None)
                if not t:
                    t = (getattr(resp.usage, "prompt_tokens", 0) or 0) + (
                        getattr(resp.usage, "completion_tokens", 0) or 0
                    )
                loop_tokens[0] = t or 0
            choice = resp.choices[0]
            if choice.message.content:
                response_text = choice.message.content
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    loop_tool_calls.append(
                        {
                            "id": tc.id,
                            "name": tc.function.name,
                            "args": json.loads(tc.function.arguments or "{}"),
                        }
                    )

        await asyncio.to_thread(_sync_call)
        accumulated_tokens += loop_tokens[0]

        if response_text:
            yield {"type": "text", "content": response_text}

        if not loop_tool_calls:
            break

        all_tool_calls.extend(loop_tool_calls)
        messages.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"]),
                        },
                    }
                    for tc in loop_tool_calls
                ],
            }
        )

        for tc in loop_tool_calls:
            yield {"type": "tool_call", "name": tc["name"], "args": tc["args"]}
            result = await execute_skill(
                tc["name"], tc["args"], skills, session_id=session_id, agent_id=agent_id
            )
            yield {"type": "tool_result", "name": tc["name"], "result": result}
            all_tool_results.append({"name": tc["name"], "result": result})
            messages.append(
                {"role": "tool", "tool_call_id": tc["id"], "content": result}
            )

    yield {
        "type": "_meta",
        "tool_calls": all_tool_calls,
        "tool_results": all_tool_results,
        "tokens_used": accumulated_tokens,
    }


# ── Main entry point ──────────────────────────────────────────────────────────


async def run_session(
    session_id: str,
    user_message: str,
    attachments: list[dict] | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Core agentic loop. Yields SSE-ready event dicts.
    Persists both the user message and assistant response to DB.
    attachments: list of {type, filename, content, mime_type} dicts from file uploads.
    """
    # Build the full message including any file attachments
    full_message = _build_message_with_attachments(user_message, attachments)

    with get_session() as session:
        sess = session.get(AgentSession, session_id)
        if not sess:
            yield {"type": "error", "message": "Session not found"}
            return

        person = session.get(Personnel, sess.personnel_id)
        if not person:
            yield {"type": "error", "message": "Personnel not found"}
            return

        cfg = session.exec(
            select(AgentConfig).where(AgentConfig.personnel_id == person.id)
        ).first()
        if not cfg:
            yield {
                "type": "error",
                "message": "Agent config not found — this person has no AI model configured",
            }
            return

        dept = (
            session.get(Department, person.department_id)
            if person.department_id
            else None
        )
        skills = session.exec(select(Skill).where(Skill.agent_id == cfg.id)).all()
        history_rows = session.exec(
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id)
            .order_by(SessionMessage.created_at)
        ).all()

        # Gather policies: dept-inherited + agent-specific (join tables, deduplicated)
        policy_names: list[str] = []
        seen_ids: set[str] = set()
        if dept:
            dept_pol_rows = session.exec(
                select(Policy)
                .join(DepartmentPolicyLink, DepartmentPolicyLink.policy_id == Policy.id)
                .where(DepartmentPolicyLink.department_id == dept.id)
                .where(Policy.is_active == True)
            ).all()
            for p in dept_pol_rows:
                if p.id not in seen_ids:
                    policy_names.append(p.name)
                    seen_ids.add(p.id)
        agent_pol_rows = session.exec(
            select(Policy)
            .join(AgentPolicyLink, AgentPolicyLink.policy_id == Policy.id)
            .where(AgentPolicyLink.agent_config_id == cfg.id)
            .where(Policy.is_active == True)
        ).all()
        for p in agent_pol_rows:
            if p.id not in seen_ids:
                policy_names.append(p.name)
                seen_ids.add(p.id)

        system_prompt = build_system_prompt(
            person,
            dept,
            list(skills),
            policy_names or None,
            rag_query=user_message[:500] if not history_rows else None,
            company_id=person.company_id,
        )
        tool_defs = build_tool_definitions(list(skills))

        # Persist user message (display original text; full_message goes to LLM)
        user_msg = SessionMessage(
            session_id=session_id,
            role="user",
            content=user_message,
        )
        session.add(user_msg)

        # Update session title from first message
        if not sess.title and user_message:
            sess.title = user_message[:60]
            session.add(sess)

        session.commit()

        # Use cfg.model for provider detection (model_version may be just a short tag like "4.6")
        model_name = cfg.model or "gemini-2.0-flash"

        provider = detect_provider(model_name)
        api_key = get_decrypted_key(provider)
        if not api_key:
            yield {
                "type": "error",
                "message": f"No active API key for provider '{provider}'. Please configure it in Settings → AI Sağlayıcılar.",
            }
            return

        gemini_history = _gemini_history(list(history_rows))

    # Stream outside the DB session to avoid holding it open
    full_text_parts: list[str] = []
    all_tool_calls: list[dict] = []
    all_tool_results: list[dict] = []

    if is_image_gen_model(model_name):
        gen = _generate_image(provider, model_name, api_key, full_message)
    elif provider == "google":
        gen = _stream_gemini(
            model_name,
            api_key,
            system_prompt,
            gemini_history,
            full_message,
            tool_defs,
            list(skills),
            session_id=session_id,
            agent_id=person.id,
        )
    elif provider == "anthropic":
        gen = _stream_anthropic(
            model_name,
            api_key,
            system_prompt,
            list(history_rows),
            full_message,
            tool_defs,
            list(skills),
            session_id=session_id,
            agent_id=person.id,
        )
    elif provider in _OPENAI_BASE_URLS:
        gen = _stream_openai_compatible(
            provider,
            model_name,
            api_key,
            system_prompt,
            list(history_rows),
            full_message,
            tool_defs,
            list(skills),
            session_id=session_id,
            agent_id=person.id,
        )
    else:
        yield {"type": "error", "message": f"Provider '{provider}' desteklenmiyor"}
        return

    tokens_used = 0
    async for event in gen:
        if event["type"] == "_meta":
            all_tool_calls = event["tool_calls"]
            all_tool_results = event["tool_results"]
            tokens_used = event.get("tokens_used") or 0
        else:
            if event["type"] == "text":
                full_text_parts.append(event["content"])
            yield event

    # Persist assistant message
    with get_session() as session:
        asst_msg = SessionMessage(
            session_id=session_id,
            role="assistant",
            content="".join(full_text_parts),
            tool_calls_json=json.dumps(all_tool_calls) if all_tool_calls else None,
            tool_results_json=json.dumps(all_tool_results)
            if all_tool_results
            else None,
            tokens_used=tokens_used if tokens_used else None,
        )
        session.add(asst_msg)

        sess = session.get(AgentSession, session_id)
        if sess:
            from datetime import datetime

            sess.updated_at = datetime.utcnow()
            session.add(sess)

        session.commit()
        session.refresh(asst_msg)
        yield {"type": "done", "message_id": asst_msg.id}
