# Backend TODO — Org Şeması & Agent Yönetimi

> Oluşturulma: 2026-05-31  
> Durum: Planlanıyor  
> Öncelik sırası: P0 → P1 → P2

---

## P0 — Org Hiyerarşisi (Acil)

### 1. Personnel modeline `manager_id` ekle

```python
class Personnel(SQLModel, table=True):
    id:             str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    organization_id: str = Field(foreign_key="organization.id")
    name:           str
    slug:           str
    role:           str | None = None
    type:           str = Field(default="human")   # "human" | "agent"
    department:     str | None = None
    manager_id:     str | None = Field(default=None, foreign_key="personnel.id")
    created_at:     datetime = Field(default_factory=datetime.utcnow)
```

**Gerekli migration:**
- Mevcut `data/app.db`'yi sıfırla veya Alembic migration yaz
- `manager_id` nullable FK (kök düğüm = NULL manager)

### 2. Org tree endpoint

```
GET /organizations/{org_id}/tree
```

Yanıt: `OrgNode[]` — iç içe JSON ağacı.

**Algoritma:**
1. Org'a ait tüm personeli çek
2. `manager_id = NULL` olanları kök olarak belirle
3. Recursive/BFS ile alt düğümleri ekle
4. Agent config verilerini (model, skills, policies) join et

```python
@app.get("/organizations/{org_id}/tree")
def get_org_tree(org_id: str) -> list[dict]:
    with Session(engine) as session:
        personnel = session.exec(
            select(Personnel).where(Personnel.organization_id == org_id)
        ).all()
    
    # id → node dict
    nodes = {p.id: p.model_dump() | {"children": []} for p in personnel}
    
    roots = []
    for node in nodes.values():
        if node["manager_id"] is None:
            roots.append(node)
        else:
            parent = nodes.get(node["manager_id"])
            if parent:
                parent["children"].append(node)
    
    return roots
```

---

## P0 — Agent Config Modeli

### 3. AgentConfig modeli

Her `Personnel` kaydının `type="agent"` olması durumunda ayrı bir `AgentConfig` tablosu:

```python
class AgentConfig(SQLModel, table=True):
    id:              str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    personnel_id:    str = Field(foreign_key="personnel.id", unique=True)
    model:           str                   # "claude-sonnet-4", "gpt-4o", ...
    model_version:   str | None = None     # "4.6", "2024-11", ...
    status:          str = Field(default="draft")  # "active" | "draft" | "inactive"
    responsible_id:  str | None = Field(default=None, foreign_key="personnel.id")
    created_at:      datetime = Field(default_factory=datetime.utcnow)
    updated_at:      datetime = Field(default_factory=datetime.utcnow)
```

**Endpoints:**
```
POST   /personnel/{id}/agent-config
GET    /personnel/{id}/agent-config
PATCH  /personnel/{id}/agent-config
```

---

## P0 — Skills & Policies (DB tabanlı)

### 4. Skill modeli

```python
class Skill(SQLModel, table=True):
    id:           str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    agent_id:     str = Field(foreign_key="agentconfig.id")
    name:         str
    version:      str
    description:  str | None = None
```

**Endpoints:**
```
GET    /personnel/{id}/skills
POST   /personnel/{id}/skills
DELETE /personnel/{id}/skills/{skill_id}
```

### 5. Policy modeli

```python
class Policy(SQLModel, table=True):
    id:              str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    organization_id: str = Field(foreign_key="organization.id")
    name:            str
    slug:            str
    scope:           str = Field(default="company")  # "company" | "department" | "agent"
    content:         str | None = None   # Markdown içeriği
    created_at:      datetime = Field(default_factory=datetime.utcnow)
```

**AgentPolicy bağlantı tablosu:**
```python
class AgentPolicy(SQLModel, table=True):
    agent_id:    str = Field(foreign_key="agentconfig.id", primary_key=True)
    policy_id:   str = Field(foreign_key="policy.id", primary_key=True)
```

**Endpoints:**
```
GET  /organizations/{org_id}/policies
POST /organizations/{org_id}/policies
GET  /personnel/{id}/policies
POST /personnel/{id}/policies/{policy_id}      # bağla
DELETE /personnel/{id}/policies/{policy_id}    # kopar
```

---

## P1 — Dosya Sistemi Entegrasyonu

### 6. `agent.md` ve `policy.md` otomatik üretimi

`data/organizations/{org-slug}/personnel/{person-slug}/` altında:
- `agent.md` — ajan tanımı (model, version, skills, responsible)
- `policy.md` — bağlı policy'lerin listesi

DB'ye kayıt atıldığında bu dosyalar da otomatik güncellenmeli (file_manager modülü).

```
data/
└── organizations/
    └── acme-corp/
        ├── company.md
        └── personnel/
            ├── codeguard/
            │   ├── agent.md
            │   └── policy.md
            └── deploybot/
                ├── agent.md
                └── policy.md
```

### 7. `company.md` CRUD endpoint

```
GET   /organizations/{org_id}/company-md
PUT   /organizations/{org_id}/company-md    # body: { content: "..." }
```

---

## P1 — API Refactor

### 8. Request body → Pydantic models

Mevcut endpoint'ler parametreleri query string'den alıyor. FastAPI best practice: `BaseModel` ile request body kullanımı.

```python
class CreatePersonnelRequest(BaseModel):
    organization_id: str
    name: str
    slug: str
    role: str | None = None
    type: str = "human"
    department: str | None = None
    manager_id: str | None = None

@app.post("/personnel")
def create_personnel(req: CreatePersonnelRequest): ...
```

### 9. Proje yapısını modüllere ayır

Şu an tüm kod `main.py`'de. Bölünmesi gereken modüller:

```
backend/
├── main.py            # sadece app tanımı ve startup
├── models.py          # tüm SQLModel tanımları
├── api/
│   ├── organizations.py
│   ├── personnel.py
│   ├── agents.py
│   └── policies.py
├── core/
│   ├── database.py    # engine, get_session
│   └── file_manager.py # MD dosya işlemleri
└── requirements.txt
```

---

## P2 — İleri Özellikler

### 10. WebSocket ile gerçek zamanlı durum güncellemesi

Agent'ların durumu (active/draft) değiştiğinde org chart'ın anlık güncellenmesi için:
```
WS /ws/organizations/{org_id}/tree
```

### 11. Bulk org import

CSV veya JSON ile toplu personel + hiyerarşi import:
```
POST /organizations/{org_id}/import
```

### 12. Agent log/activity API

Her agent'ın ne zaman ne yaptığını kaydeden aktivite log endpoint'i:
```
GET  /personnel/{id}/activity?limit=50
POST /personnel/{id}/activity
```

---

## Teknik Borç Notları

| # | Konu | Açıklama |
|---|------|----------|
| T1 | CORS | Production'da `allow_origins=["*"]` kapatılmalı, origin whitelist yapılmalı |
| T2 | Auth | Şu an auth yok. MVP sonrası JWT veya API key ile koruma |
| T3 | Validation | Slug uniqueness kontrolü eksik (aynı org içinde aynı slug mümkün) |
| T4 | Error handling | 404 / 409 response'ları eksik; HTTPException kullanılmalı |
| T5 | DB migration | Alembic entegrasyonu yoktur; şema değişikliklerinde DB sıfırlanıyor |
