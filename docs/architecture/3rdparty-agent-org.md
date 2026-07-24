---
sidebar_position: 1
---

# Mimari: Agentic Organization

## Genel Bakış

| Katman | Teknoloji | Notlar |
|---|---|---|
| **Backend** | FastAPI + SQLModel + SQLite | Modüler router yapısı, Alembic migration |
| **Frontend** | SvelteKit 5 + Tailwind CSS | Svelte 5 runes (`$state`, `$derived`, `$effect`) |
| **Şifreleme** | Fernet (AES-256) | API anahtarları, Git token'ları, sosyal medya kimlik bilgileri |
| **Git** | GitPython | YAML tabanlı senkronizasyon, iki aşamalı onay akışı |
| **Scheduler** | APScheduler | Otonom akış cron zamanlaması |
| **Deployment** | Docker Compose + Nginx | Self-hosted, prodüksiyon + dev konfigürasyonları |

---

## Klasör Yapısı

```
agentic-organization/
├── backend/
│   ├── main.py              # Router kaydı + startup hooks
│   ├── models.py            # SQLModel ORM modelleri
│   ├── schemas.py           # Pydantic istek/yanıt şemaları
│   ├── database.py          # SQLite engine + session context manager
│   ├── api/
│   │   ├── auth.py             # Login, invite, setup wizard, JWT
│   │   ├── companies.py        # Şirket CRUD + stats
│   │   ├── departments.py      # Departman CRUD (parent_id hiyerarşi)
│   │   ├── personnel.py        # Personel + AgentConfig + org-tree
│   │   ├── skills.py           # CompanySkill CRUD + AgentSkillLink
│   │   ├── policies.py         # Politika yönetimi
│   │   ├── onboarding.py       # AI Onboarding (search/chat/generate/create)
│   │   ├── sessions.py         # AI oturumları + SSE akışı
│   │   ├── flows.py            # Otonom Akışlar (APScheduler)
│   │   ├── task_requests.py    # Görev yönlendirme + insan onayı
│   │   ├── a2a.py              # A2A delegasyon + otomatik rapor derleme
│   │   ├── providers.py        # AI sağlayıcı anahtar yönetimi
│   │   ├── dashboard.py        # Canlı telemetri + SLA metrikleri
│   │   ├── audit.py            # Denetim günlüğü
│   │   └── git_sync.py         # Git pull/push/diff/PR
│   ├── core/
│   │   └── security.py      # Fernet şifreleme/çözme
│   └── services/
│       ├── agent_runtime.py    # AI çalışma motoru (çoklu sağlayıcı)
│       ├── memory_service.py   # Uzun dönem hafıza özeti (oturum kapatma)
│       ├── flow_runner.py      # Cron akış çalıştırıcı + görsel üretim
│       └── onboarding_agent.py # DDG araması + LLM sohbeti + toplu oluşturma
│
├── frontend/
│   └── src/
│       ├── lib/
│       │   ├── api/             # Tip güvenli fetch istemcileri
│       │   ├── components/ui/   # Bespoke bileşenler (Button, Dialog, Badge...)
│       │   ├── i18n/            # TR/EN çeviri sözlükleri
│       │   └── stores/
│       │       └── company.svelte.ts  # Aktif şirket state'i
│       └── routes/
│           ├── +layout.svelte   # Şirket switcher + dil seçici + nav
│           ├── +page.svelte     # Dashboard (telemetri + SLA)
│           ├── chat/            # Ajan sohbet arayüzü
│           ├── departments/
│           ├── personnel/
│           ├── skills/
│           ├── policies/
│           ├── org-chart/
│           ├── jobs/            # Görev talepleri + A2A delegasyon
│           └── settings/        # AI sağlayıcılar + Git + entegrasyonlar
│
├── data/                     # SQLite DB
├── docker-compose.yml          # Geliştirme (hot-reload)
└── docker-compose.prod.yml     # Prodüksiyon (Nginx + rate limiting)
```

### Bulut Dağıtımı

`*.agent.fab.engineering` wildcard DNS kaydı ile çok kiracılı çalışma:

```
demo.agent.fab.engineering       → demo çalışma alanı
fabrikayazilim.agent.fab.engineering → şirkete özel çalışma alanı
app.agent.fab.engineering        → ana giriş noktası
```

Nginx wildcard `server_name` → tek Docker stack. Subdomain'den şirket slug'ı otomatik çözümlenir.

```

---

## Veri Modeli

```
Company
  ├── id, name, slug, sector, website
  │
  ├──< Department (company_id FK)
  │      ├── id, name, slug, description, goals
  │      ├── parent_id FK → Department (self-referential, null = kök birim)
  │      └── policies_json  (JSON dizisi)
  │
  └──< Personnel (company_id FK)
         ├── id, name, slug, title, role, type (human|agent)
         ├── department_id FK → Department
         ├── manager_id FK → Personnel (self-referential)
         │
         └── AgentConfig (1:1)
                ├── model, model_version, status (draft|active|inactive)
                ├── responsible_id FK → Personnel
                └──< Skill
                       └── name, version, description
```

Ek tablolar:

| Tablo | Amaç |
|---|---|
| `AppConfig` | Platform geneli anahtar-değer ayarları |
| `ProviderKey` | Şifrelenmiş AI API anahtarları |
| `GitConfig` | GitHub PAT bağlantı ayarları (şirket başına) |
| `SyncLog` | Pull/push/commit geçmişi |
| `ChangeRequest` | Değişiklik Talebi (durum, onay zamanları, commit SHA) |
| `Flow` | Otonom Akış tanımı (schedule, prompt, enabled) |
| `InboxMessage` | Gelen Kutusu mesajları (kaynak türü, okundu durumu) |
| `TaskRequest` | Görev Talebi (filtreler, atanan ajan, sorumlu kullanıcı) |

---

## Backend Mimarisi

### Router Yapısı

`main.py` ince bir orkestratör olarak çalışır:

```python
app.include_router(auth_router)         # /auth
app.include_router(companies_router)    # /companies
app.include_router(dept_router)         # /departments
app.include_router(personnel_router)    # /personnel + /org-tree
app.include_router(skills_router)       # /skills + /builtin-tools
app.include_router(policies_router)     # /policies
app.include_router(providers_router)    # /providers
app.include_router(sessions_router)     # /sessions
app.include_router(flows_router)        # /flows
app.include_router(a2a_router)          # /a2a
app.include_router(task_router)         # /tasks
app.include_router(dashboard_router)    # /dashboard
app.include_router(audit_router)        # /audit
app.include_router(git_router)          # /git
app.include_router(onboarding_router)   # /onboarding
```

Her router kendi prefix'i ile tanımlanır. Trailing slash sorunundan kaçınmak için route'lar `""` (boş string) ile tanımlanır, `/` ile değil.

### Startup Hooks

Uygulama başlarken sırasıyla:
1. `init_db()` — Tablolar oluşturulur (yoksa)
2. `run_seed()` — Örnek veri yüklenir (tablo boşsa)
3. `_sync_env_config()` — `.env` → `AppConfig` tablosu
4. `_sync_env_provider_keys()` — `.env` API anahtarları şifrelenerek kaydedilir

### Güvenlik

- API anahtarları ve Git token'ları Fernet (AES-256) ile şifrelenir
- Şifreleme anahtarı `data/.secret` dosyasında tutulur (chmod 600)
- Hiçbir zaman düz metin anahtar API yanıtı olarak dönmez

---

## Frontend Mimarisi

### Svelte 5 Runes

State yönetimi Svelte 5 runes ile yapılır:

```typescript
// stores/company.svelte.ts
let _list = $state<Company[]>([]);
let _active = $state<Company | null>(null);

export const companyStore = {
  get list() { return _list; },
  get active() { return _active; },
  async load() { ... },
  setActive(c: Company) { _active = c; },
  async create(name: string) { ... },
};
```

### i18n

Çeviri sistemi reaktif locale state üzerine kuruludur:

```typescript
// i18n/index.svelte.ts
let _locale = $state<Locale>('tr');

export const i18n = {
  get locale() { return _locale; },
  set locale(v: Locale) { _locale = v; },
  t(key: TranslationKey): string { ... }
};
```

Desteklenen diller: TR / EN

### Şirket Filtreleme

Tüm liste sayfaları (`departments`, `personnel`, `org-chart`) aktif şirkete göre filtreli veri çeker:

```typescript
departments = await deptApi.list(companyStore.active?.id);
```

---

## Git Senkronizasyon Servisi

`GitSyncService` sınıfı iki yönlü senkronizasyonu yönetir:

**DB → YAML (Push):**
- Tüm ajan kayıtları `agents/{slug}/agent.yaml` formatında dışa aktarılır
- Değişiklikler `git add + commit + push` ile repoya gönderilir
- `auto_pr=True` ise doğrudan push yerine PR açılır

**YAML → DB (Pull):**
- Repo clone/fetch edilir
- YAML dosyaları parse edilerek `upsert` yapılır (slug bazlı eşleştirme)
- Tüm işlemler `SyncLog` tablosuna kaydedilir

---

## Platform Kapsamı

| Bileşen | Açıklama |
|---|---|
| Organizasyon yönetimi | Şirket + departman hiyerarşisi + personel CRUD, iç içe `parent_id` desteği |
| AI sağlayıcılar | Fernet şifreli anahtar yönetimi — Anthropic, OpenAI, Google, Mistral, Qwen, Ollama, LM Studio |
| AI Onboarding | Web araştırması + çok turlu LLM sohbeti + toplu varlık oluşturma |
| Git entegrasyonu | Pull/push/diff/PR, YAML I/O, iki aşamalı onay akışı (dept_head → admin → commit) |
| Çoklu şirket | Navbar şirket switcher + i18n (TR/EN) |
| Skill sistemi | `builtin \| mcp \| http \| function` tipleri, `AgentSkillLink` çoka-çok bağlantı |
| Agent runtime | SSE akışı, çoklu provider yönlendirmesi, agentic döngü, uzun dönem hafıza |
| Chat UI | Markdown/Mermaid render, ajan bilgi paneli, oturum geçmişi |
| A2A delegasyon | `pending_approval → running → completed → otomatik rapor` akışı |
| Otonom Akışlar | APScheduler cron + tüm sağlayıcılar + DashScope görsel üretim yönlendirmesi |
| Dashboard | Şirket telemetrisi, kullanıcı telemetrisi, ajan SLA metrikleri |
| Kimlik doğrulama | JWT + davet sistemi, 5 rol kademesi, şifre zorunluluğu, şifre değiştirme akışı |
| Güvenlik | Nginx hız sınırlama, JWT_SECRET uyarısı, Pydantic şema doğrulama, şirket düzeyi yetkilendirme |
| Yedekleme | S3/R2/MinIO yedekleme, `sqlite3.backup()` API, yedekleme geçmişi |
| Sosyal Medya | Instagram Graph API + WhatsApp Business Cloud API builtin skill'leri |
| Telegram | Bot API bildirimleri (davet, şifre sıfırlama), şifreli token saklama |
| Denetim Günlüğü | Tüm mutasyon endpoint'leri için `log_action()` kaydı |

---

## İlgili Dokümanlar

- [Kurulum](../getting-started/installation.md)
- [Kullanım Kılavuzu](../getting-started/agent-usage.md)
- [Provider Anahtar Yönetimi](./provider-key-management.md)
- [Agent Runtime Mimarisi](./runtime.md)
- [Skill Tipleri](./skill-types.md)
- [A2A İşbirliği Mimarisi](../product/a2a-architecture.md)
