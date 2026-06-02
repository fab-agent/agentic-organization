---
sidebar_position: 1
---

# Mimari: 3rdParty Agent Organization

## Genel Bakış

| Katman | Teknoloji | Notlar |
|---|---|---|
| **Backend** | FastAPI + SQLModel + SQLite | Modüler router yapısı |
| **Frontend** | SvelteKit 5 + Tailwind CSS | Svelte 5 runes (`$state`, `$derived`, `$effect`) |
| **Şifreleme** | Fernet (AES-256) | API anahtarları ve Git token'ları için |
| **Git** | GitPython | YAML tabanlı senkronizasyon |
| **CLI** | TypeScript + @clack/prompts | Kurulum sihirbazı |
| **Deployment** | Docker Compose | Tek komutla tam stack |

---

## Klasör Yapısı

```
3rdparty-agent-org/
├── backend/
│   ├── main.py              # Router kaydı + startup hooks
│   ├── models.py            # SQLModel ORM modelleri
│   ├── schemas.py           # Pydantic istek/yanıt şemaları
│   ├── database.py          # SQLite engine + session context manager
│   ├── seed.py              # İlk açılışta örnek veri (2 şirket)
│   ├── api/
│   │   ├── companies.py        # Şirket CRUD + stats
│   │   ├── departments.py      # Departman CRUD (parent_id hiyerarşi)
│   │   ├── personnel.py        # Personel + AgentConfig + Skill CRUD
│   │   ├── providers.py        # AI sağlayıcı anahtar yönetimi
│   │   ├── git_sync.py         # Git pull/push/diff/logs
│   │   ├── change_requests.py  # Değişiklik Talepleri onay akışı
│   │   ├── flows.py            # Otonom Akışlar (cron zamanlayıcı)
│   │   ├── inbox.py            # Gelen Kutusu mesajları
│   │   └── task_requests.py    # Görev Talepleri + ajan eşleştirme
│   ├── core/
│   │   └── security.py      # Fernet şifreleme/çözme
│   └── services/
│       ├── provider_service.py   # API anahtar testi (httpx)
│       └── git_service.py        # GitPython işlemleri + YAML I/O
│
├── frontend/
│   └── src/
│       ├── lib/
│       │   ├── api/             # Tip güvenli fetch istemcileri
│       │   │   ├── client.ts    # Temel fetch wrapper
│       │   │   ├── companies.ts
│       │   │   ├── departments.ts
│       │   │   ├── personnel.ts
│       │   │   ├── orgtree.ts
│       │   │   ├── providers.ts
│       │   │   └── git.ts
│       │   ├── components/ui/   # Bespoke bileşenler (Button, Dialog, Badge...)
│       │   ├── i18n/            # TR/EN/DE/ES çeviri sözlükleri
│       │   └── stores/
│       │       └── company.svelte.ts  # Aktif şirket state'i
│       └── routes/
│           ├── +layout.svelte   # Şirket switcher + dil seçici + nav
│           ├── +page.svelte     # Dashboard
│           ├── departments/
│           ├── personnel/
│           ├── org-chart/
│           └── settings/        # AI sağlayıcılar + Git
│
├── packages/cli/             # `3pa` CLI sihirbazı
├── data/                     # SQLite DB + Git önbelleği
└── docker-compose.yml
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
app.include_router(companies_router)    # /companies
app.include_router(dept_router)         # /departments
app.include_router(personnel_router)    # /personnel + /org-tree
app.include_router(providers_router)    # /providers
app.include_router(git_router)          # /git
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

Desteklenen diller: TR / EN / DE / ES (~50 çeviri anahtarı)

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

## Mevcut Durum

| Faz | Durum | Kapsam |
|---|---|---|
| **F1** | ✅ Tamamlandı | Backend modüler mimari, şirket + departman + personel CRUD |
| **F2** | ✅ Tamamlandı | Provider anahtar yönetimi (Fernet şifreleme, test, UI) |
| **F3** | ✅ Tamamlandı | CLI kurulum sihirbazı (`3pa init`) |
| **F4** | ✅ Tamamlandı | Git entegrasyonu (pull/push/diff/PR, YAML I/O) |
| **F5** | ✅ Tamamlandı | Çoklu şirket desteği + i18n (TR/EN/DE/ES) |
| **F6A** | ✅ Tamamlandı | Skill tipleştirme: `builtin \| mcp \| http \| function`, `config_json` şemaları, `is_active` bayrağı |
| **F6B** | ✅ Tamamlandı | Agent runtime: SSE akışı, çoklu provider yönlendirmesi (Gemini/Anthropic), agentic döngü (maks 8 iter.) |
| **F6C** | ✅ Tamamlandı | Chat UI (Markdown/Mermaid render), agent bilgi paneli, A2A delegasyon + onay akışı |
| **F7** | ✅ Tamamlandı | Kimlik doğrulama (JWT + davet sistemi), rol hiyerarşisi, profil sayfası |
| **F8** | ✅ Tamamlandı | Departman hiyerarşisi (`parent_id`), Değişiklik Talepleri onay akışı, GitHub PAT entegrasyonu, Otonom Akışlar (cron), Görev Talepleri, Gelen Kutusu (30s polling) |

---

## İlgili Dokümanlar

- [Kurulum](../getting-started/installation.md)
- [Kullanım Kılavuzu](../getting-started/agent-usage.md)
- [Provider Anahtar Yönetimi](./provider-key-management.md)
- [Agent Runtime Mimarisi](./runtime.md)
- [Skill Tipleri](./skill-types.md)
- [A2A İşbirliği Mimarisi](../product/a2a-architecture.md)
