"""
AI Onboarding Service
─────────────────────
1. Web search (ddgs) for company context
2. Multi-turn LLM conversation to gather org details
3. Structured JSON org generation
4. Bulk entity creation
"""
import json
import asyncio
import re
from datetime import datetime
from typing import AsyncGenerator

from sqlmodel import select

from database import get_session
from models import (
    Company, Department, DepartmentPolicyLink, Personnel, AgentConfig, CompanySkill,
    Policy, AgentSkillLink, ProviderKey, OnboardingSession,
)
from core.security import decrypt
from services.agent_runtime import detect_provider


# ── Session persistence ───────────────────────────────────────────────────────

def get_onboarding_session(company_id: str) -> dict | None:
    """Return saved onboarding session for company, or None."""
    with get_session() as session:
        row = session.exec(
            select(OnboardingSession).where(OnboardingSession.company_id == company_id)
        ).first()
        if not row:
            return None
        return {
            "phase": row.phase,
            "search_context": row.search_context or "",
            "messages": json.loads(row.messages_json) if row.messages_json else [],
            "structure": json.loads(row.structure_json) if row.structure_json else None,
            "updated_at": row.updated_at.isoformat(),
        }


def save_onboarding_session(
    company_id: str,
    phase: str,
    search_context: str | None = None,
    messages: list | None = None,
    structure: dict | None = None,
) -> None:
    """Upsert onboarding session progress to DB."""
    with get_session() as session:
        row = session.exec(
            select(OnboardingSession).where(OnboardingSession.company_id == company_id)
        ).first()
        if row is None:
            row = OnboardingSession(company_id=company_id, phase=phase)
            session.add(row)
        row.phase = phase
        if search_context is not None:
            row.search_context = search_context
        if messages is not None:
            row.messages_json = json.dumps(messages, ensure_ascii=False)
        if structure is not None:
            row.structure_json = json.dumps(structure, ensure_ascii=False)
        row.updated_at = datetime.utcnow()
        session.commit()


def delete_onboarding_session(company_id: str) -> None:
    """Remove session after successful completion."""
    with get_session() as session:
        row = session.exec(
            select(OnboardingSession).where(OnboardingSession.company_id == company_id)
        ).first()
        if row:
            session.delete(row)
            session.commit()


# ── Web search ────────────────────────────────────────────────────────────────

def search_company(company_name: str, max_results: int = 6) -> str:
    """Return a short text context from DDG search results."""
    try:
        from ddgs import DDGS
        snippets = []
        with DDGS() as d:
            results = list(d.text(
                f'"{company_name}" şirket sektör hakkında',
                region="tr-tr",
                max_results=max_results,
            ))
            for r in results:
                snippets.append(f"• {r['title']}: {r['body'][:200]}")

        if not snippets:
            # English fallback
            with DDGS() as d:
                results = list(d.text(
                    f'"{company_name}" company sector about',
                    max_results=max_results,
                ))
                for r in results:
                    snippets.append(f"• {r['title']}: {r['body'][:200]}")

        return "\n".join(snippets) if snippets else ""
    except Exception as e:
        return f"[Arama yapılamadı: {e}]"


# ── Provider selection ────────────────────────────────────────────────────────

def _get_best_key() -> tuple[str, str, str] | None:
    """Return (provider, model, api_key) for the first active key. Prefers anthropic → openai → google."""
    priority = ["anthropic", "openai", "google", "qwen", "mistral"]
    default_models = {
        "anthropic": "claude-sonnet-4-6",
        "openai":    "gpt-4o",
        "google":    "gemini-2.0-flash",
        "qwen":      "qwen-plus",
        "mistral":   "mistral-large-latest",
    }
    with get_session() as session:
        keys = session.exec(
            select(ProviderKey).where(ProviderKey.status == "active")
        ).all()
        key_map = {k.provider: k for k in keys}

    for provider in priority:
        if provider in key_map:
            row = key_map[provider]
            return provider, default_models[provider], decrypt(row.encrypted_key)
    return None


# ── Simple LLM call (non-streaming, for structured output) ───────────────────

async def _call_llm(messages: list[dict], provider: str, model: str, api_key: str,
                   max_tokens: int = 8192) -> str:
    """Single blocking call, returns assistant text."""
    def _sync():
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            sys_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
            user_msgs = [m for m in messages if m["role"] != "system"]
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=sys_msg,
                messages=user_msgs,
            )
            return resp.content[0].text

        elif provider == "google":
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key)
            sys_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
            history = []
            for m in messages:
                if m["role"] == "system":
                    continue
                history.append({"role": "user" if m["role"] == "user" else "model",
                                 "parts": [{"text": m["content"]}]})
            resp = client.models.generate_content(
                model=model,
                contents=history,
                config=types.GenerateContentConfig(
                    system_instruction=sys_msg,
                    max_output_tokens=max_tokens,
                ),
            )
            return resp.text

        else:  # openai-compatible
            from openai import OpenAI
            base_url_map = {
                "openai": "https://api.openai.com/v1",
                "qwen":   "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            }
            client = OpenAI(api_key=api_key, base_url=base_url_map.get(provider, "https://api.openai.com/v1"))
            resp = client.chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens
            )
            return resp.choices[0].message.content or ""

    return await asyncio.to_thread(_sync)


# ── Streaming LLM call (for chat UI) ─────────────────────────────────────────

async def stream_onboarding_chat(
    messages: list[dict],
    provider: str,
    model: str,
    api_key: str,
) -> AsyncGenerator[str, None]:
    """Stream text tokens from the LLM for the onboarding chat."""

    async def _anthropic():
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        sys_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]

        def _sync():
            return client.messages.create(
                model=model, max_tokens=2048,
                system=sys_msg, messages=user_msgs,
            )
        resp = await asyncio.to_thread(_sync)
        yield resp.content[0].text

    async def _google():
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        sys_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        history = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
            for m in messages if m["role"] != "system"
        ]

        def _sync():
            return client.models.generate_content(
                model=model, contents=history,
                config=types.GenerateContentConfig(system_instruction=sys_msg),
            )
        resp = await asyncio.to_thread(_sync)
        yield resp.text

    async def _openai_compat():
        from openai import OpenAI
        base_url_map = {"openai": "https://api.openai.com/v1", "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"}
        client = OpenAI(api_key=api_key, base_url=base_url_map.get(provider, "https://api.openai.com/v1"))

        def _sync():
            return client.chat.completions.create(model=model, messages=messages, max_tokens=2048)
        resp = await asyncio.to_thread(_sync)
        yield resp.choices[0].message.content or ""

    if provider == "anthropic":
        async for chunk in _anthropic():
            yield chunk
    elif provider == "google":
        async for chunk in _google():
            yield chunk
    else:
        async for chunk in _openai_compat():
            yield chunk


# ── System prompt ─────────────────────────────────────────────────────────────

ONBOARDING_SYSTEM = """Sen bir kurumsal yapay zeka organizasyon danışmanısın.
Şirketlerin yapay zeka ajanlarını, departmanlarını, yeteneklerini ve politikalarını kurmasına yardım ediyorsun.

GÖREV AKIŞI:
1. Şirket hakkında web araştırması sonuçlarını değerlendir ve kendinle tanış
2. Kullanıcıya sırayla şu bilgileri topla (her seferinde 1-2 soru, toplam 3-5 tur):
   a) Takım büyüklüğü ve temel departmanlar/roller
   b) En çok vakit kaybedilen tekrarlayan işler ve kullanılan araçlar (Excel, PDF, SCADA, CRM...)
   c) Hassas veriler ve AI'ın kesinlikle yapmaması gerekenler (KVKK, güvenlik sınırları)
   d) Kısa vadeli öncelikler ve hedefler
3. Kullanıcının cevaplarına göre bir organizasyon yapısı oluştur
4. Yapıyı kısa özetle ve <READY_TO_GENERATE/> sinyali ver

ZORUNLU KURAL — <READY_TO_GENERATE/> KULLANIMI:
- Bu sinyali YALNIZCA kullanıcı en az 3 soruya gerçek cevap verdikten SONRA kullanabilirsin
- İlk mesajında, tanışma mesajında veya henüz soru sormadan KESİNLİKLE kullanma
- Yeterli bilgi (takım büyüklüğü + tekrarlayan işler + hassasiyet sınırları) toplandıktan sonra
  son mesajının SONUNA ekle: <READY_TO_GENERATE/>

Üslup: Samimi, profesyonel, kısa ve net. Listeler ve emoji kullanabilirsin.
HER ZAMAN Türkçe konuş."""

STRUCTURE_SYSTEM = """Sen kıdemli bir kurumsal AI organizasyon mimarısın. Verilen onboarding konuşmasına göre şirkete özel, GERÇEKÇİ ve KULLANIMA HAZIR bir organizasyon yapısını JSON formatında üretirsin.
SADECE geçerli JSON döndür — açıklama, markdown fence veya başka hiçbir metin ekleme.

# KRİTİK KURALLAR

## Model seçimi
Tüm ajanların "model" alanına DAİMA "{available_model}" yaz. Başka model adı uydurma.

## Skill content (EN ÖNEMLİ KURAL)
Her company_skill'in "content" alanı MİNİMUM 300 karakter olmalı ve şu Markdown başlıklarını içermeli:

## <Yetenek Adı> Yeteneği
(1-2 cümle genel tanım)

## Nasıl Kullanılır
(numaralı adımlar, en az 3 adım)

## Girdi Formatı
(beklenen girdi; tablo veya madde listesi)

## Çıktı Formatı
(üreteceği çıktının yapısı ve formatı)

## Örnek
(şirketin sektörüne özel somut, gerçek bir senaryo)

## Guardrails / Sınırlamalar
(en az 3 madde: neyi yapmaz, ne zaman onay ister, hangi verilere dokunmaz)

TEK CÜMLELIK, JENERİK VEYA PLACEHOLDER CONTENT KESİNLİKLE YASAK.
İçerik şirketin gerçek sektörüne ve konuşmadan elde edilen araç/süreç bilgilerine özel olmalı.

## Policy content (EN ÖNEMLİ KURAL)
Her policy'nin "content" alanı MİNİMUM 250 karakter olmalı ve şu başlıkları içermeli:

## <Politika Adı>

## Politika Amacı
(neden bu politika gerekli, hangi riski önlüyor)

## Kapsam
(kimler ve hangi sistemler bu politikaya tabidir)

## Kurallar
(madde listesi — somut, uygulanabilir kurallar)

## Gerekçe
(şirkete özel neden, sektör veya yasal bağlam)

## İstisnalar
(hangi durumlarda istisna uygulanabilir, hangi koşulda)

## Uyum Kontrolü
(nasıl denetlenir, ihlalde ne olur)

TEK PARAGRAFLIK KURAL CÜMLESİ YASAK.

## Diğer kurallar
- description alanları 1 net cümle, content ise yukarıdaki tam yapı (ikisini karıştırma).
- Slug'lar lowercase-kebab ve Türkçe karaktersiz (ğ→g, ş→s, ı→i, ö→o, ü→u, ç→c).
- Her ajan en az 2 gerçek skill slug'ına bağlı olmalı; var olmayan slug referanslama.
- humans listesindeki name alanı: konuşmada gerçek isim geçtiyse onu kullan. Geçmediyse "Ahmet Yılmaz" gibi uydurma isimler YASAK — bunun yerine unvanı kullan, örn. "Satış Direktörü", "Yazılım Mimarı", "Pazarlama Uzmanı". Isim alanına unvan/rol yazılabilir, bu tercih edilir.

# JSON şeması
{{
  "departments": [
    {{"name": "string", "slug": "string (lowercase-kebab)", "description": "string", "goals": "string (\\n ile ayır)"}}
  ],
  "humans": [
    {{"name": "string", "title": "string", "role": "string", "department_slug": "string or null"}}
  ],
  "agents": [
    {{"name": "string", "slug": "string", "title": "string", "department_slug": "string",
      "model": "{available_model}", "skills": ["skill_slug_1", "skill_slug_2"],
      "system_prompt_hint": "string (bu ajanın ne yapacağını 2 cümlede açıkla)"}}
  ],
  "company_skills": [
    {{"name": "string", "slug": "string", "skill_type": "builtin",
      "description": "string (1 cümle)",
      "content": "string (yukarıdaki 6 başlıklı markdown yapısı, öz ve net)"}}
  ],
  "policies": [
    {{"name": "string", "slug": "string", "scope": "company | department | agent",
      "department_slug": "string or null",
      "content": "string (yukarıdaki 6 başlıklı markdown yapısı, öz ve net)"}}
  ]
}}

# Üretilecek miktar
- 3-5 departman
- 4-8 insan personel (unvan ve rol ile)
- 3-6 ajan (her biri en az 2 yeteneğe sahip, model = "{available_model}")
- 4-8 şirket yeteneği (sektöre özel, yapılandırılmış)
- 3-5 politika (en az 1 şirket geneli, tam yapılandırılmış)
"""


# ── Bulk entity creator ───────────────────────────────────────────────────────

def create_org_from_structure(company_id: str, structure: dict, fallback_model: str = "qwen-plus") -> dict:
    """Create all entities from the generated structure. Returns summary."""
    summary = {"departments": 0, "humans": 0, "agents": 0, "skills": 0, "policies": 0}

    with get_session() as session:
        dept_map: dict[str, str] = {}  # slug → id

        # 1. Departments
        for d in structure.get("departments", []):
            dept = Department(
                company_id=company_id,
                name=d["name"],
                slug=d.get("slug", d["name"].lower().replace(" ", "-")),
                description=d.get("description"),
                goals=d.get("goals"),
            )
            session.add(dept)
            session.flush()
            dept_map[d["slug"]] = dept.id
            summary["departments"] += 1

        # 2. Company skills
        skill_id_map: dict[str, str] = {}  # slug → company_skill_id
        for sk in structure.get("company_skills", []):
            skill = CompanySkill(
                company_id=company_id,
                name=sk["name"],
                slug=sk.get("slug", sk["name"].lower().replace(" ", "-")),
                skill_type=sk.get("skill_type", "builtin"),
                description=sk.get("description"),
                content=sk.get("content", f"## {sk['name']}\n\n{sk.get('description', '')}"),
                is_active=True,
            )
            session.add(skill)
            session.flush()
            skill_id_map[sk["slug"]] = skill.id
            summary["skills"] += 1

        # 3. Human personnel
        human_map: dict[str, str] = {}  # name → personnel_id
        for h in structure.get("humans", []):
            dept_id = dept_map.get(h.get("department_slug", "")) or None
            person = Personnel(
                company_id=company_id,
                name=h["name"],
                slug=re.sub(r"[^a-z0-9]+", "-", h["name"].lower().strip()),
                title=h.get("title"),
                role=h.get("role"),
                type="human",
                department_id=dept_id,
            )
            session.add(person)
            session.flush()
            human_map[h["name"]] = person.id
            summary["humans"] += 1

        # 4. Agents
        for ag in structure.get("agents", []):
            dept_id = dept_map.get(ag.get("department_slug", "")) or None
            agent_person = Personnel(
                company_id=company_id,
                name=ag["name"],
                slug=ag.get("slug", re.sub(r"[^a-z0-9]+", "-", ag["name"].lower())),
                title=ag.get("title"),
                type="agent",
                department_id=dept_id,
            )
            session.add(agent_person)
            session.flush()

            cfg = AgentConfig(
                personnel_id=agent_person.id,
                model=ag.get("model") or fallback_model,
                model_version=None,
                status="active",
            )
            session.add(cfg)
            session.flush()

            # Assign skills
            for skill_slug in ag.get("skills", []):
                skill_id = skill_id_map.get(skill_slug)
                if skill_id:
                    session.add(AgentSkillLink(
                        agent_config_id=cfg.id,
                        company_skill_id=skill_id,
                    ))

            summary["agents"] += 1

        # 5. Policies
        dept_policy_names: dict[str, list[str]] = {}  # dept_id → [policy_name]
        for pol in structure.get("policies", []):
            dept_id = dept_map.get(pol.get("department_slug", "")) or None
            policy = Policy(
                company_id=company_id,
                name=pol["name"],
                slug=pol.get("slug", pol["name"].lower().replace(" ", "-")),
                scope=pol.get("scope", "company"),
                department_id=dept_id,
                content=pol.get("content", f"## {pol['name']}\n\n"),
                is_active=True,
            )
            session.add(policy)
            session.flush()
            summary["policies"] += 1
            if dept_id:
                dept_policy_names.setdefault(dept_id, []).append(pol["name"])

        # Create DepartmentPolicyLink records (many-to-many, replaces policies_json)
        for dept_id, names in dept_policy_names.items():
            dept_obj = session.get(Department, dept_id)
            if not dept_obj:
                continue
            # Also keep policies_json in sync for legacy readers
            dept_obj.policies_json = json.dumps(names, ensure_ascii=False)
            session.add(dept_obj)

        # policy name → id map for creating links
        policy_name_to_id: dict[str, str] = {}
        for pol in structure.get("policies", []):
            dept_id = dept_map.get(pol.get("department_slug", "")) or None
            if dept_id:
                # find the Policy we just created by slug
                pass  # will be resolved below after flush

        # Build name→id map from DB records (flushed above)
        all_policies = session.exec(
            select(Policy).where(Policy.company_id == company_id)
        ).all()
        for p in all_policies:
            policy_name_to_id[p.name] = p.id

        # Create DepartmentPolicyLink rows
        for dept_id, names in dept_policy_names.items():
            for name in names:
                pid = policy_name_to_id.get(name)
                if pid:
                    session.add(DepartmentPolicyLink(department_id=dept_id, policy_id=pid))

        # 6. Mark company as onboarded
        company = session.get(Company, company_id)
        if company:
            company.ai_onboarded = True
            session.add(company)

        session.commit()

    delete_onboarding_session(company_id)
    return summary


# ── Generate structure from conversation ──────────────────────────────────────

def _repair_json(raw: str) -> str:
    """
    Attempt to fix a truncated JSON string by closing any open string literals
    and unclosed arrays/objects. Only used as a last-resort fallback.
    """
    stack: list[str] = []
    in_string = False
    escape_next = False

    for ch in raw:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in ("}","]") and stack and stack[-1] == ch:
            stack.pop()

    suffix = ""
    if in_string:
        suffix += '"'          # close the unterminated string
    suffix += "".join(reversed(stack))  # close any open arrays/objects
    return raw + suffix


async def generate_org_structure(
    company_name: str,
    conversation: list[dict],
    provider: str,
    model: str,
    api_key: str,
) -> dict:
    """Ask the LLM to generate a structured JSON org from the conversation."""
    convo_text = "\n".join(
        f"{'Kullanıcı' if m['role'] == 'user' else 'AI'}: {m['content']}"
        for m in conversation
        if m["role"] != "system"
    )

    prompt = f"""Şirket adı: {company_name}

Onboarding konuşması:
{convo_text}

Yukarıdaki bilgilere dayanarak şirket için organizasyon yapısını JSON formatında oluştur.
Slug'lar Türkçe karaktersiz olmalı (ğ→g, ş→s, ı→i, ö→o, ü→u, ç→c).
SADECE JSON döndür."""

    messages = [
        {"role": "system", "content": STRUCTURE_SYSTEM.format(available_model=model)},
        {"role": "user", "content": prompt},
    ]

    # Use 16 000 output tokens — Turkish text + JSON overhead is heavy on tokens.
    # Anthropic claude-sonnet-4-6 supports up to 16 384 max output tokens.
    raw = await _call_llm(messages, provider, model, api_key, max_tokens=16000)

    # Extract JSON from response (strip markdown fences if present)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"```(?:json)?\s*", "", raw)
        raw = raw.rstrip("`").strip()

    # Primary parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError as primary_err:
        # Attempt lightweight repair (closes truncated string/array/object)
        try:
            repaired = _repair_json(raw)
            result = json.loads(repaired)
            # Warn in logs but continue — partial structure is still useful
            import logging
            logging.getLogger("app").warning(
                "generate_org_structure: JSON was truncated and auto-repaired. "
                f"Original error: {primary_err}. "
                "Consider reviewing the generated structure for completeness."
            )
            return result
        except json.JSONDecodeError:
            raise ValueError(
                f"AI geçersiz JSON üretiyor (onarılamadı): {primary_err}. "
                "Lütfen daha kısa bir yapı isteyerek tekrar deneyin."
            ) from primary_err
