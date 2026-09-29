"""Agent memory: generate and load session summaries."""

from datetime import datetime

from sqlmodel import select

from database import get_session
from models import AgentConfig, AgentMemory, AgentSession, SessionMessage


async def generate_session_summary(session_id: str) -> None:
    """Background task: summarize a closed session and store as AgentMemory."""
    with get_session() as db:
        sess = db.get(AgentSession, session_id)
        if not sess:
            return

        messages = db.exec(
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id)
            .order_by(SessionMessage.created_at)
        ).all()

        if len(messages) < 2:
            return  # Not enough content to summarize

        # Build conversation text
        convo_lines = []
        for m in messages:
            role_label = "User" if m.role == "user" else "Agent"
            convo_lines.append(f"{role_label}: {m.content[:500]}")
        convo_text = "\n".join(convo_lines[-30:])  # last 30 messages max

        # Get agent config and provider
        agent_cfg = db.exec(
            select(AgentConfig).where(AgentConfig.personnel_id == sess.personnel_id)
        ).first()
        if not agent_cfg:
            return

        from services.model_routing import ModelRoutingError, resolve_model

        try:
            resolved = resolve_model(agent_cfg.model, agent_cfg.provider)
        except ModelRoutingError:
            return

        summary_prompt = (
            "The following is a conversation between a user and an AI agent. "
            "Extract 2-4 key facts the agent learned, decisions made, or tasks completed. "
            "Write a brief paragraph (max 100 words) in plain English starting with 'In a previous session,'\n\n"
            + convo_text
        )

        try:
            summary = _call_summary_llm(
                provider=resolved.protocol,
                model=resolved.model,
                api_key=resolved.api_key,
                prompt=summary_prompt,
                base_url=resolved.base_url,
            )
        except Exception:
            return

        if not summary.strip():
            return

        memory = AgentMemory(
            personnel_id=sess.personnel_id,
            session_id=session_id,
            summary=summary.strip(),
            created_at=datetime.utcnow(),
        )
        db.add(memory)
        db.commit()


def _call_summary_llm(
    provider: str, model: str, api_key: str, prompt: str, base_url: str | None = None
) -> str:
    """`provider` is the protocol: "anthropic", "google", or "openai" (any
    OpenAI-compatible endpoint at `base_url`)."""
    if provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text

    if provider == "google":
        from google import genai

        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(model=model, contents=prompt)
        return resp.text or ""

    import openai

    client = openai.OpenAI(api_key=api_key or "none", base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=256,
    )
    return resp.choices[0].message.content or ""


def load_agent_memories(personnel_id: str, limit: int = 3) -> list[str]:
    """Return the most recent memory summaries for an agent."""
    with get_session() as db:
        rows = db.exec(
            select(AgentMemory)
            .where(AgentMemory.personnel_id == personnel_id)
            .order_by(AgentMemory.created_at.desc())
            .limit(limit)
        ).all()
        return [r.summary for r in rows]
