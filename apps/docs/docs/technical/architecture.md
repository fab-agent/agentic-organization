---
sidebar_position: 1
---

# Mimari

Bu bölüm BT ekipleri ve geliştiriciler içindir. İş kullanıcıları için [Kullanım Kılavuzu](/guide/onboarding) yeterlidir.

## Bileşenler

```
 Tarayıcı ──► Nginx ──► Arayüz (SvelteKit)
                 └────► Backend (FastAPI) ──► PostgreSQL + pgvector
                              │
                              ├──► LLM sağlayıcıları (Anthropic, OpenAI, Google, Mistral, Qwen, yerel, özel)
                              ├──► Harici araçlar (MCP, HTTP, veritabanları, Instagram/WhatsApp)
                              ├──► Telegram, Resend (e-posta), S3 uyumlu depolama, GitHub
                              │
 3pa + opencode ───► /v1 gateway, /workstation, /mcp   (geliştirici iş istasyonu)
 fab (terminal) ───► /workspaces, /work-review         (departman çalışma alanı)
```

| Bileşen | Teknoloji | Görev |
|---|---|---|
| **Backend** | FastAPI, SQLModel, Alembic, APScheduler | API, ajan çalışma zamanı, zamanlanmış işler |
| **Arayüz** | SvelteKit 5 (Svelte runes), Tailwind, TR/EN | Web arayüzü |
| **Veritabanı** | PostgreSQL 16 + pgvector (geliştirmede SQLite) | Tüm veri, anlamsal arama |
| **`packages/cli`** | TypeScript | `3pa` geliştirici CLI'ı |
| **`packages/agent-plugin`** | TypeScript | opencode eklentisi (politika, denetim) |
| **`packages/tui`** | Rust, Ratatui | `fab` terminal istemcisi |
| **`sandbox/`** | Docker | Geliştirici sandbox'ı ve departman çalışma alanı imajı |

## Depo düzeni

| Dizin | İçerik |
|---|---|
| `backend/api/` | Her kaynak için bir yönlendirici (`auth`, `personnel`, `flows`, `a2a`, `gateway`, `workstation`, `work_review`, `workspaces` …) |
| `backend/services/` | İş mantığı: ajan çalışma zamanı, akış çalıştırıcı, politika motoru, denetim zinciri, RAG, Git, Telegram … |
| `backend/models.py` | Tüm tablolar |
| `backend/migrations/` | Alembic geçişleri |
| `frontend/` | SvelteKit uygulaması |
| `docs/adr/` | Mimari karar kayıtları ([indeks](/developer-notes/overview#mimari-karar-kayıtları-adr)) |
| `.github/workflows/` | Bileşen başına CI |

## Veri modeli (özet)

```
Şirket ──< Departman ──< Personel ──── Ajan yapılandırması ──< Yetenek
   │                        │                 │
   │                        │            Oturum ──< Mesaj
   │                        │                 └── Hafıza (oturum özeti), gömme vektörleri
   │
   ├── Politika (şirket | departman | ajan)
   ├── Akış (cron)  ·  Görev talebi  ·  A2A talebi  ·  Gelen kutusu mesajı
   ├── Değişiklik talebi (iki aşamalı onay)
   ├── Sağlayıcı anahtarı  ·  Git yapılandırması  ·  Telegram  ·  Veritabanı bağlantısı
   └── Kullanıcı ──< Şirket üyeliği (rol)
```

Geliştirici iş istasyonu ve departman çalışma alanı katmanlarının kendi tabloları vardır (denetim zinciri, token durumu, çalışma alanı, iş incelemesi puanları). Bkz. ilgili bölümler.

## Başlangıç ve zamanlanmış işler

Uygulama açılırken veritabanı geçişleri (Alembic) çalışır, ilk kurulumda tohum veri yazılır ve ortamdaki sağlayıcı anahtarları içe aktarılır. Birden çok işlemle (worker) çalışırken **yalnızca bir işlem** zamanlayıcıyı ve Telegram sorgulamasını çalıştırır (kilit dosyası ile); diğerleri yalnızca istek karşılar.

Zamanlayıcı (UTC) şu işleri yürütür:

| İş | Sıklık |
|---|---|
| Kullanıcı akışları | Her akışın kendi cron'u; akış listesi dakikada bir eşitlenir |
| RAG indeksleyici | 15 dakikada bir (yeni oturum yanıtları, görev sonuçları, hafızalar) |
| Denetim önem puanlaması | 10 dakikada bir (kapalıysa hiçbir şey yapmaz) |
| İş incelemesi toplama / temizlik / puanlama | Saatlik / günlük / saatlik (şirket açtıysa) |

## Çok kiracılı alt alan adları

Her şirkete kendi alt alan adını verebilirsiniz (`sirket.agent.sirketim.com`): wildcard DNS kaydı tek sunucuya işaret eder, Nginx hepsini aynı uygulamaya iletir, arayüz alt alan adından şirketi `/tenant/resolve` ile çözer (giriş sayfasında şirket adı görünür, olmayan alt alan adı 404 verir). Veriler şirket bazında ayrılır. Adım adım kurulum için depodaki `CLOUD_DEPLOY.md` dosyasına bakın.

## Frontend notları

- **Svelte 5 runes.** Durum `$state`, `$derived`, `$effect` ile yönetilir.
- **Şirkete duyarlı veri yükleme.** Sayfalar, aktif şirket değiştiğinde yeniden yüklenir; bu yüzden hem ilk yükleme (`onMount`) hem şirket değişimi (`$effect`) ayrı ele alınır ve API çağrılarına `company_id` verilir.
- **i18n.** İki dil (`tr`, `en`); eksik çeviri Türkçeye düşer. Dil seçimi tarayıcıda saklanır.
