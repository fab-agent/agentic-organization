---
sidebar_position: 0
---

# Changelog

Platform güncellemelerinin kronolojik kaydı.

---

## v1.2 — 9 Eylül 2026

> **Ajan Yürütme Katmanı (Agentic OS).** Bu sürüm, geliştirici personaların kendi
> iş istasyonlarında **opencode** ile çalışmasını sağlayan yeni bir katman
> getiriyor. Tüm model trafiği merkezî bir gateway'den geçer, her komut
> çalıştırılabilir politikalarla değerlendirilir, her eylem değiştirilemez bir
> denetim zincirine yazılır. Web arayüzü değişmedi — bu katman onun yanında,
> opsiyonel olarak çalışır. Mimari kararların tamamı `docs/adr/` altındadır
> (ADR-0001 … ADR-0013). Ayrıntılı dokümantasyon → **Ajan Yürütme Katmanı**
> bölümü.

### Yeni Özellikler

**Merkezî LLM Gateway (ADR-0004):**
- OpenAI uyumlu proxy (`POST /v1/chat/completions`, `GET /v1/models`). Ajanlar
  kendi API anahtarını görmez; persona bearer token'ı ile gateway'e bağlanır.
- Upstream, şirketin `ProviderKey.base_url` kaydından çözülür — "kendi anahtarını
  getir" (BYO). Anthropic, OpenAI, Google, Mistral, Qwen ve OpenAI uyumlu her
  endpoint desteklenir.
- SSE streaming birebir geçirilir; `stream_options.include_usage` enjekte
  edilerek akışlı çağrıların token tüketimi de ölçülür.
- Guardrail'lar (`services/gateway_limits.py`): model allow-list, persona başına
  hız sınırı ve günlük/aylık token kotası (`GatewayUsage`), `GET /gateway/usage`.
  Varsayılanların tamamı serbest.

**Çalıştırılabilir Politika Motoru (ADR-0005):**
- Saf `evaluate()` (fail-closed) + veritabanı destekli `decide()`. Persona'dan
  şirket → departman → ajan kapsamı çözülür.
- Rollout modu `off | dry_run | enforce` (`PolicyConfig`, en-özel-kazanır,
  varsayılan `dry_run`). Fail-closed verdict'ler her modda engeller.
- `bashlex` AST tabanlı komut eşleştirme — string kaçışlarına dayanıklı.
  Yıkıcı komutlar için yerleşik taban kurallar.
- Üst departman politikaları alt departmanlara miras kalır (`_department_chain`).
- opencode plugin'i `tool.execute.before` içinde `/policy/decide` çağırır;
  `enforce` modda `deny`/`ask` verdict'inde araç çağrısı başarısız olur.

**Değiştirilemez Denetim Zinciri (ADR-0006):**
- sha256 hash zinciri, kiracı başına ayrı zincir (`AuditEvent`, `chain_key`,
  `seq`). `GET /audit/chain/verify` zincirin bütünlüğünü doğrular.
- gateway çağrısı / politika kararı / araç olayı tek bir `record()` üzerinden
  hem zincire hem eski `AuditLog` tablosuna yazılır.
- Harici çıpalama (`services/audit_anchor.py`): periyodik olarak zincir başlıkları
  yerel `jsonl` dosyasına ve S3 Object Lock (COMPLIANCE) kovasına yazılır;
  `check_anchors()` kesme/yeniden yazma tespit eder. `GET/POST /audit/chain/anchors`.
- Postgres'te advisory lock ile eşzamanlılık güvenliği.

**LLM Denetim Önem Skorlaması (ADR-0013):**
- 10 dakikada bir çalışan iş: son denetim olaylarını OpenAI uyumlu bir modele
  gönderip 1–5 risk puanı, kategori ve tek satır gerekçe alır; sonucu `AuditSeverity`
  yan tablosuna yazar (zincir hiç değiştirilmez).
- Puan ≥ eşik → sorumlu insana `InboxMessage` + şirketin Telegram admin sohbetine
  uyarı.
- Şirket bazında opt-in (`severity.enabled:<company_id>`).
- Politika geri beslemesi: `severity.autopolicy` açıkken bir şirket bir saat
  içinde eşik sayıda yüksek-önem olay biriktirirse, o şirketin politika modu
  otomatik olarak `enforce`'a çekilir ve yöneticiler bilgilendirilir.
- Ayarlar: `severity.{enabled,model,threshold,batch,alert_default,autopolicy,autopolicy_count}`.

**`3pa` İş İstasyonu CLI (ADR-0009):**
- `3pa init` — kurulum sihirbazı; `3pa login` — persona seç, workstation token al
  (`~/.config/3pa/session.json`); `3pa refresh` / `3pa logout` (`--revoke`).
- `3pa run` — opencode'u yönetilen sandbox içinde başlatır.
- `3pa policy` — persona için etkin politika kurallarını gösterir.
- `3pa audit verify` — sunucudaki denetim zincirini doğrular.
- `3pa stop` / `3pa signal` — çalışan sandbox oturumunu imzalı komutla durdurur.
- `3pa doctor` — sandbox ön koşullarını kontrol eder.
- `POST /workstation/heartbeat` — periyodik durum + imzalı komut kanalını yoklar.

**Yönetilen opencode Yapılandırması (ADR-0011):**
- İmzalı `/.well-known/opencode` (Ed25519, `services/wellknown_sign.py`) +
  `/.well-known/opencode/pubkey`. Anahtar rotasyonu `previous_key_id` ile.
- Sandbox içinde `/etc/opencode/opencode.json` olarak enjekte edilir — opencode
  Linux'ta bunu "managed config" olarak, kullanıcı ayarlarının üstünde okur.

**Backend MCP Sunucusu (ADR-0001):**
- `POST /mcp` — JSON-RPC. Persona'nın skill'lerini (`build_tool_definitions` /
  `execute_skill`) ve `org_policies` aracını sunar.

### Güvenlik

**Persona Kimliği ve Kısa Ömürlü Kimlik Bilgileri (ADR-0007):**
- Access token (`typ=persona`, ~60 dk) + refresh token (`typ=persona_refresh`,
  `aud=refresh`, ~12 sa), her ikisinde `jti`.
- `POST /workstation/persona-token`, `.../refresh`, `.../revoke` (sahip veya
  persona'nın kendisi).
- İptal kontrolü fail-closed (`api/deps.py`): `RevokedToken` + `PersonaTokenState`
  (not-before işareti). `revocation_maintenance` işi bayat oturumları otomatik
  iptal eder ve eski iptal satırlarını temizler.
- OIDC token değişimi (`services/oidc.py`, JWKS) — `oidc.enabled` olmadıkça kapalı,
  otomatik kullanıcı oluşturmaz.

**Prompt Injection Savunması (ADR-0010):**
- **Katman 1 — köken/taint:** dış içerik (webfetch, dosya, araç çıktısı)
  "untrusted" olarak işaretlenir.
- **Katman 2 — yapısal guardrail'lar:** `sandbox/base-prompt.md` üzerinden
  enjekte edilen kalıcı sistem direktifleri.
- **Katman 3 — untrusted → ask:** untrusted bağlamdan tetiklenen yan etkili
  araçlar onaya düşer.
- **Katman 4 — egress allowlist:** sandbox yalnızca `egress` filtreleyen proxy
  üzerinden çıkabilir; internal-only Docker ağının başka rotası yoktur.
- **Katman 5 — imzalı komut kanalı:** `PersonaCommand` tablosu, Ed25519 ile
  imzalanmış sarmalanmış komutlar; `3pa` heartbeat sırasında doğrular.
- Katman 6 (çıktı taraması) sonraki faza bırakıldı.

**Sandbox İzolasyon Sıkılaştırması (ADR-0002):**
- `cap_drop: ALL`, `security_opt: no-new-privileges`, `pids_limit`, `mem_limit`,
  `cpus` sınırları. Ajanın etki alanı bu konteynerdir.
- `entrypoint.sh` tüm `OPENCODE_*` ortam değişkenlerini temizler (config bypass'ını
  engellemek için).
- Egress proxy `tinyproxy` `FilterDefaultDeny` + genişletilmiş regex allowlist
  ile çalışır.

### Altyapı

**Postgres + pgvector'a tam geçiş:**
- RAG artık ana veritabanında (`EmbeddingRecord` / `RagIndexState`); `sqlite-vec`
  bırakıldı. Postgres'te `pgvector` (`<=>` + HNSW), SQLite'ta numpy brute-force.
- `db` servisi (`pgvector/pgvector:pg16`) base/prod/cloud compose dosyalarına
  eklendi. `database.py` dialect-farkında.
- Canlı test dağıtımı SQLite → Postgres taşındı; 390 satır / 23 tablo, denetim
  zinciri taşıma sonrası bütünlüğü doğrulandı.

**Sürüm Yayınlama İş Akışı (ADR-0012):**
- `release.yml` — sandbox/egress imajları → GHCR, `3pa` esbuild bundle,
  plugin/cli → GitHub Packages.
- opencode **1.18.26**'ya sabitlendi; `docs/architecture/version-compat.md`
  uyumluluk matrisi eklendi.
- Yeni CI iş akışları: `sandbox.yml`, `cli.yml`, path-scoped tetikleyiciler,
  `adr-guard`.

---

## v1.1.2 — 15 Temmuz 2026

### Lisans

- Lisans **MIT + Commons Clause** olarak güncellendi. Kendi kurumunuz için kullanmak, fork etmek ve katkıda bulunmak ücretsizdir. Yeniden satış, white-label veya ücretli servis için iletişim gereklidir.
- `README.md` ve landing page lisans referansları güncellendi.

---

## v1.1.1 — 14 Temmuz 2026

### İyileştirmeler

**AI Sağlayıcı Ayarları Yeniden Tasarımı:**
- Sağlayıcılar artık iki ayrı bölümde gösteriliyor: **Lokal Modeller** (Ollama, LM Studio) ve **Bulut API Servisleri** (Anthropic, OpenAI, Google, Mistral, Qwen).
- `Server` ve `Globe` ikon başlıkları ile bölüm açıklamaları eklendi.

### Hata Düzeltmeleri

**AI Provider Anahtarı Eklenemiyor:**
- `invalid` durumundaki sağlayıcı kartlarında "Sil" butonu artık gösteriliyor. Önceden yalnızca `active` durumdaki kartlarda görünüyordu; bu nedenle hatalı kaydedilen bir key silinemiyor ve yeniden denenemiyor durumdaydı.
- Silme işlemi artık soft-delete yapıyor: DB satırı korunduğundan backend yeniden başladığında `.env`'den key tekrar eklenmez.

**Dashboard i18n:**
- Dashboard sayfasındaki tüm Türkçe hardcoded string'ler `t()` çağrılarıyla değiştirildi.
- 45 yeni i18n anahtarı eklendi: telemetri bölümü, SLA tablosu, hızlı erişim, oturum durumu, hafıza kartları ve güncelleme banner'ı.

**Organizasyon Şeması:**
- İngilizce nav ve sayfa başlığı `'Organization'` / `'Org Chart'` → `'Organization Chart'` olarak düzeltildi.

**AI Provider Ayarları:**
- `invalid` durumundaki sağlayıcı kartlarında "Sil" butonu artık görünüyor (önceden yalnızca `active` durumda gösteriliyordu).

---

## v1.1 — 14 Temmuz 2026

### Prodüksiyon Hazırlığı

**Tek Komut Kurulum:**
- `install.sh` — `curl | bash` ile sunucuya tam prodüksiyon kurulumu yapar; Docker kontrolü, `.env` sihirbazı, SSL sertifikası alma ve servis başlatma adımlarını otomatikleştirir.
- `setup-env.sh` — interaktif `.env` sihirbazı; `JWT_SECRET` ve `ENCRYPTION_KEY` `openssl rand` ile otomatik üretilir.
- İsteğe bağlı güncelleme bildirimi kaydı (e-posta + domain) sihirbaz sonunda sunulur; MIT lisanslı, herhangi bir kısıtlama yoktur.

**Prodüksiyon Docker Yapılandırması:**
- `backend/Dockerfile.prod` — `--reload` kaldırıldı, 2 worker ile çalışır.
- `frontend/Dockerfile.prod` — Multi-stage build; `npm run build` + `node build` ile prodüksiyon sunumu.
- `docker-compose.prod.yml` — Bağımsız (override değil) tam prodüksiyon konfigürasyonu.
- `nginx.prod.conf.template` — HTTPS + HTTP→HTTPS redirect + Let's Encrypt sertifika desteği; `install.sh` domain ile somut `nginx.conf` üretir.

**Güncelleme Bildirimi (UI):**
- Backend `GET /system/version` endpoint'i GitHub Releases API'yi sorgulayarak güncel sürümü kontrol eder (1 saatlik önbellek).
- Dashboard'da yeni sürüm varken sarı banner gösterilir; GitHub release sayfasına link içerir.

**Ajan SLA & Başarı Oranı:**
- `GET /dashboard/agent-sla` — her ajan için oturum sayısı, token kullanımı, flow başarı oranı ve görev tamamlama oranını döndürür.
- Dashboard'da yöneticilere tablo olarak gösterilir; %90+ yeşil, %70–89 sarı, altı kırmızı.

**Dokümantasyon:**
- Yeni **Sistem Gereksinimleri** sayfası: sunucu özellikleri, açık portlar, domain gereksinimleri, AI sağlayıcıları.
- **Kurulum** sayfası genişletildi: prodüksiyon kurulum adımları, SSL yapılandırması, certbot cron job, Nginx template açıklaması eklendi.

---

## v1.0 — 14 Temmuz 2026

### Lokal Model Desteği (Ollama & LM Studio)

- **Ollama** ve **LM Studio** birinci sınıf provider olarak eklendi.
- Ayarlar → AI Sağlayıcılar'da bu sağlayıcılar seçildiğinde API key yerine **Sunucu Adresi** alanı gösterilir; varsayılan adres otomatik doldurulur (`localhost:11434` / `localhost:1234`).
- Bağlan'a basıldığında `/v1/models` endpoint'i ping'lenir; sunucuda yüklü modeller otomatik çekilir.
- Ajan sayfasında lokal modeller artık seçilebilir; tam agentic loop (tool call → execute → feed back) desteğiyle çalışır.

### Değişiklik Talebi (Change Request) Akışı

- Ajan düzenleme panelindeki **"Güncelle"** butonu **"Talep Oluştur"** olarak değiştirildi; düzenlemeler artık doğrudan kayıt yerine onay akışına giriyor.
- Onay akışı: `submitted → dept_head_approved → admin_approved → committed` (GitHub'a YAML commit).
- GitConfig şirket bazlı bulunamazsa global kayda fallback yapılıyor; GitHub commit artık tüm senaryolarda tetikleniyor.
- Liste satırındaki Git ikonu ve ham JSON change request popup'ı kaldırıldı — değişiklik talebi yalnızca düzenleme panelinden gönderilebilir.

### Araç Yönetimi İyileştirmeleri

- "Özel Yetenek Ekle" bölümü **"Araç Ekle"** olarak yeniden adlandırıldı (TR + EN).
- Dahili araç listesi frontend'e hardcoded değil, backend `/builtin-tools` endpoint'inden dinamik olarak çekiliyor.
- Araç formundaki **Versiyon** alanı kaldırıldı; araçlar `1.0` ile oluşturulur, GitHub entegrasyonu versiyonlama sağlar.

### Arşivleme (Soft-Delete)

- Ajan silme işlemi **arşivleme** ile değiştirildi: `status = inactive` olarak işaretlenir, veri silinmez.
- Liste varsayılan olarak arşivlenenları gizler; istatistik kartındaki **Arşivlenmiş** sayısına tıklayarak gösterilebilir.
- Yeni backend endpoint: `POST /personnel/{id}/archive`.

### Güvenlik

- JWT_SECRET varsayılan değerde bırakıldığında başlangıçta `CRITICAL` log uyarısı eklendi.

---

## v0.9 — 12 Temmuz 2026

### Token Telemetrisi ve Hafıza Düzeltmeleri

#### Token Takibi Düzeltmesi
- `_stream_openai_compatible` ve `_stream_anthropic` fonksiyonlarında token sayısı her araç-kullanım döngüsünde sıfırlanıyordu; artık tüm iterasyonlar boyunca biriktirilip tek `_meta` event'inde iletiliyor.
- `SessionMessage.tokens_used` artık qwen dahil tüm sağlayıcılarda doğru kaydediliyor.
- Qwen `resp.usage` yapısındaki `total_tokens` yokluğuna karşı `prompt_tokens + completion_tokens` yedek hesaplama eklendi.

#### Dashboard/Me Düzeltmesi
- `/dashboard/me` endpoint'i kullanıcının kendi personnel_id'siyle session arıyordu (her zaman 0 sonuç döndürüyordu). Artık kullanıcının sorumlu olduğu ajanların sessionları sorgulanıyor; sorumlu ajan yoksa tüm şirket ajanlarına fallback yapılıyor.
- `/dashboard/stats` şirket genelinde token ve hafıza verilerini doğru topluyor.

#### Uzun Dönem Hafıza — Qwen Desteği
- `memory_service.py`: `_prov_for_model()` yardımcısı ve qwen sağlayıcı fallback eklendi; qwen ajanlarının oturumları kapatıldığında artık `agentmemory` kaydı oluşturuluyor.
- `_call_summary_llm()`: qwen / mistral için OpenAI uyumlu istemci dalı eklendi; `base_url` dinamik olarak `ProviderKey` tablosundan okunuyor.

---

### Akış Koşucusu (Flow Runner) Geliştirmeleri

#### Qwen Görsel Üretimi Akışlarda
- `flow_runner.py`: `is_image_gen_model()` tespiti eklendi; `qwen-image-*`, `wanx-*`, `flux-*` model adlarıyla tetiklenen akışlar otomatik olarak DashScope görev API'sine yönlendiriliyor.
- `_generate_image_sync()`: DashScope asenkron görev API'si (gönder + yokla) senkron akış koşucusunda çalışacak şekilde httpx ile implement edildi; 80 saniyelik zaman aşımı ile sonuç Markdown görsel olarak inbox'a iletiliyor.
- `_call_llm()`: qwen / mistral için OpenAI uyumlu dal eklendi.

#### Görev Yönlendirme Düzeltmesi
- `task_requests.py`: `_route_agent()` yalnızca eski `Skill` tablosunu kontrol ediyordu. Artık `AgentSkillLink/CompanySkill` tablosu da sorgulanıyor; her iki yapıda da skill eşleşmesi aranıyor.
- `_model_to_provider()` yardımcısı eklendi; görev koşucusu artık ajan modelinden sağlayıcıyı otomatik çıkarıyor (qwen dahil).

---

### Entegrasyon Testleri

#### GitHub Entegrasyonu
- `fab-agent/fabrika-yazilim-org` reposu mevcut token ile bağlandı ve doğrulandı.

#### Telegram
- Bot entegrasyonu doğrulandı; bildirimler aktif.

#### PostgreSQL — Odoo Uyumlu Veritabanı
- Odoo MRP 2 şemasıyla uyumlu PostgreSQL 18 veritabanı sisteme eklendi.
- DSN: `postgresql://odoo_agent:***@127.0.0.1:5432/fabrika_odoo`
- Tablolar: `mrp_production`, `mrp_bom`, `mrp_bom_line`, `mrp_workorder`, `product_template`, `product_product`
- pg_hba.conf md5 kimlik doğrulaması yapılandırıldı.

#### Otonom Akışlar
- APScheduler tabanlı akışlar `*/15` ve `*/30` cron zamanlamasıyla test edildi ve doğrulandı.

---

## v0.8 — 9 Temmuz 2026

### Özellikler

#### AI Onboarding
- Ayarlar → AI Sağlayıcılar altında **"AI ile Kur"** butonu eklendi (yalnızca henüz onboarding yapılmamış şirketlerde görünür).
- Tıklandığında sidebar/topnav olmayan tam ekran `/onboarding` sayfası açılır.
- **Aşama 1 — Araştırma:** DuckDuckGo üzerinden şirket web araştırması yapılır; sonuçlar onboarding AI bağlamına aktarılır.
- **Aşama 2 — Konuşma:** AI Türkçe 3-5 soru sorar (ekip büyüklüğü, bölümler, öncelikli süreçler). Kullanıcı cevapladıkça yapı netleşir; AI hazır olduğunda `<READY_TO_GENERATE/>` sinyali gönderir.
- **Aşama 3 — Önizleme:** Oluşturulacak departman, insan, ajan, yetenek ve politika sayıları kart + açılır bölümler (collapsible) ile gösterilir. "← Sohbete Dön" ile revizyon yapılabilir.
- **Aşama 4 — Oluştur:** Tek tıkla tüm varlıklar veritabanına yazılır (FK sırası: departman → yetenek → insan → ajan+AgentConfig+skill bağlantısı → politika). `ai_onboarded` bayrağı `true`'ya set edilir; kullanıcı ana uygulamaya yönlendirilir.
- Yeni backend servisi: `services/onboarding_agent.py` — DDG araması, çok turlu LLM sohbeti (SSE akışı), yapılandırılmış JSON üretimi, toplu varlık oluşturma.
- Yeni API modülü: `api/onboarding.py` — 5 endpoint (`/onboarding/status/{id}`, `/search`, `/chat`, `/generate`, `/create`).
- `Company` modeline `ai_onboarded: bool` alanı + Alembic migration eklendi.
- `ddgs>=6.0` bağımlılığı `requirements.txt`'e eklendi.

#### Yetenekler & Politikalar Sayfaları (v0.7)
- `/skills` sayfası: YapiTabs + yetenek kart ızgarası, 3-mod side panel (görüntüle/düzenle/oluştur), Markdown editörü (Yaz/Önizle sekmeleri), CR onay akışı.
- `/policies` sayfası: kapsam filtre hapları (Tümü/Şirket/Bölüm/Ajan), aynı Markdown editörü ve CR akışı.

#### Sidebar Yeniden Yapısı (v0.7)
- Bölümler/İnsanlar/Ajanlar/Yetenekler/Politikalar nav öğeleri kaldırıldı; bunların yerine **Göstergeler** (dashboard) ve **Yapı** (tüm yapı sayfaları) olmak üzere iki üst düzey öğe eklendi.
- `YapiTabs` bileşeni her yapı sayfasında sekme navigasyonu sağlar.

---

## v0.6 — 9 Temmuz 2026

### Özellikler

#### Canlı Dashboard & AI Telemetrisi
- Dashboard tamamen yeniden yazıldı: şirkete özel gerçek zamanlı metrikler (insan/ajan sayısı, aktif ajan, bugünkü/toplam oturum, token kullanımı, hafıza kaydı sayısı).
- Kullanıcıya özel bölüm: platformda bir personel kaydına bağlı kullanıcılar kendi oturumlarını, token kullanımını ve uzun dönem hafıza özetlerini doğrudan dashboard'da görür.
- Yeni backend endpoint'leri: `GET /dashboard/stats` (şirket telemetrisi) ve `GET /dashboard/me` (kullanıcı telemetrisi).
- `/auth/me` yanıtı artık her şirket üyeliği için `personnel_id` alanını döner.

#### Şirket Bilgi Paneli (company.md)
- Navbar'daki şirket adının yanına dişli ikonu eklendi; tıklanınca vizyon, misyon, değerler ve hedefleri gösteren sağ side panel açılır.
- Yönetici ve üzeri roller düzenleyebilir; kullanıcılar salt okunur görür.
- Dashboard'daki eski company.md kart widget'ı kaldırıldı.

#### Personel Side Panel
- İnsan personele satır tıklamasıyla açılan sağ panel: bilgi (departman, yönetici, e-posta, platform durumu), son oturumlar, uzun dönem hafıza özetleri.
- Panel 3 modlu: `view` (bilgi görüntüleme) → `edit` (formu panel içinde düzenleme, geri oku ile view'e dönüş) → `create` (yeni personel).
- Personel oluşturma/düzenleme popup diyaloğu tamamen kaldırıldı.

#### Ajan Hafızası Görüntüleme
- Yeni backend endpoint: `GET /sessions/memories?personnel_id=...` — kapalı oturumların AI tarafından oluşturulan özetlerini döner.
- Personel side panel'inde ve kullanıcı dashboard'unda oturum listesi ve hafıza özetleri görünür.

#### Telegram Bildirim Entegrasyonu
- Resend e-posta entegrasyonu tamamen kaldırıldı; davet ve şifre sıfırlama bildirimleri artık Telegram Bot API üzerinden iletilir.
- **Ayarlar → Entegrasyonlar** sekmesi: bot token ve admin chat ID yapılandırması, test mesajı gönderme, bot bilgisi gösterimi.
- Bot token AES-256 ile şifreli saklanır; `TelegramConfig` tablosu Alembic migration ile eklendi.

#### AI Sağlayıcılar Sekmesi Yeniden Tasarımı
- Ayarlar → Sağlayıcılar: sadece anahtar girilmiş sağlayıcılar gösterilir; yapılandırılmamışlar "Sağlayıcı Ekle" dropdown akışıyla eklenir.
- Geçersiz durumdaki eski kayıtlar temizlendi.

### UI İyileştirmeleri

- **Ayarlar tabları kaydırılabilir:** 6 sekme küçük ekranlarda yatay scroll ile erişilebilir; scrollbar gizli.
- **Sidebar daraltma:** Masaüstünde sidebar `w-60 → w-16` arasında geçiş yapar; ikonlar görünür, etiketler gizlenir.
- **Şirket seçici navbara taşındı:** Sidebar alt kısmındaki büyük şirket kartı kaldırıldı; navbar'a kompakt dropdown olarak eklendi.
- **Sağ panel overlay:** Ajanlar ve personel sayfalarındaki side panel içeriği itmek yerine üzerine gelir (`position: fixed`).

---

## v0.5 — 9 Temmuz 2026

### Güvenlik

#### Şirket Düzeyi Yetkilendirme
- Tüm API uç noktaları (`companies`, `departments`, `personnel`, `org-tree`, `sessions`) artık JWT sahibinin ilgili şirkete üyeliğini doğrular.
- Bir kullanıcı birden fazla şirkette üye olabilir; liste endpoint'leri yalnızca erişimi olan şirketlerin verilerini döner.
- `check_company_membership()` ve `_get_person_and_check_membership()` yardımcı fonksiyonları eklendi.

#### Pydantic Doğrulaması
- Auth endpoint'leri (`login`, `setup`, `change-password`, `invite`) artık `body: dict` yerine güçlü tipli Pydantic şemaları kullanır.
- E-posta normalizasyonu ve minimum şifre uzunluğu (8 karakter) doğrulaması schema seviyesinde uygulanır.

#### SSE Oturum Temizliği
- Sunucu-taraflı olaylar (SSE) kesildiğinde oturum durumu `active`'den `idle`'a geçer; artık askıda kalmaz.

#### Şifre Değiştirme Zorunluluğu
- Davet edilen kullanıcılar ilk girişte `/set-password` sayfasına yönlendirilir; bu sayfa atlanamaz.

### Altyapı

#### Veritabanı Migrasyonları (Alembic)
- Alembic entegrasyonu tamamlandı; artık `alembic revision --autogenerate` ile şema değişiklikleri izlenebilir.
- SQLite `ALTER TABLE` desteği için `render_as_batch=True` aktif.

#### Yapılandırılmış JSON Loglama
- `logs/app.log` dosyasına JSON formatında günlük; 30 günlük otomatik rotasyon.
- HTTP istek/yanıt logging middleware eklendi (method, path, status, ms).

#### Nginx Hız Sınırlama
- Üretim ortamı için `docker-compose.prod.yml` + `nginx.conf`: login endpoint'i IP başına dakikada 5 istek, genel API 60 istek.

#### Cloudflare Tunnel
- HTTPS kurulumu için Cloudflare Tunnel rehberi README'ye eklendi (Option C).

### Özellikler

#### S3/R2/MinIO Yedekleme
- **Ayarlar → Yedekleme** sekmesi: S3, Cloudflare R2 veya MinIO uyumlu depolama yapılandırması.
- `sqlite3.backup()` API ile güvenli çevrimiçi yedek alma, boto3 ile yükleme.
- Yedekleme geçmişi (son 20 yedek), anlık yedek alma butonu, kimlik bilgileri şifreli saklanır.

#### Sosyal Medya Ajan Skill'leri
- `instagram_post` builtin skill: Instagram Business hesabına Graph API v21.0 üzerinden fotoğraf paylaşımı.
- `whatsapp_send` builtin skill: WhatsApp Business Cloud API üzerinden metin mesajı gönderimi.
- **Ayarlar → Sosyal Medya** sekmesi: IG User ID + Access Token, WA Phone Number ID + Access Token yapılandırması; kimlik bilgileri AES-256 ile şifreli saklanır.
- Ajan yapılandırmasında bu skill'leri builtin olarak ekleyerek herhangi bir ajan sosyal medya paylaşımı yapabilir.

---

## v0.4 — 2 Temmuz 2026

### Yeni Özellikler

#### Alibaba Qwen Entegrasyonu
- **Ayarlar → AI Sağlayıcılar** sayfasına Alibaba Qwen (DashScope) eklendi.
- Desteklenen modeller: `qwen-max`, `qwen-plus`, `qwen-turbo`, `qwen-long`
- DashScope'un OpenAI uyumlu API'si üzerinden çalışır; ajan çalışma zamanında tam araç (tool-use) desteği mevcuttur.

#### İlk Kurulum Sihirbazı
- Sistemi yeni kurarken sabit bir yönetici şifresi yerine **kurulum formu** gösterilir (n8n tarzı).
- Form alanları: Ad Soyad, Şirket Adı, E-posta, Şifre, Şifre Tekrar.
- Form gönderildiğinde ilk kullanıcı `founder` rolüyle oluşturulur ve sisteme otomatik giriş yapılır.
- DB'de kullanıcı mevcut olduğunda `/setup` sayfası devre dışı kalır (403).

### Geliştirmeler
- Frontend dil seçenekleri Türkçe ve İngilizce ile sınırlandırıldı (Deutsch ve Español kaldırıldı).

---

## v0.3 — 23 Haziran 2026

### Yeni Özellikler

#### Denetim Günlüğü (Audit Log) — Tam Kapsam
- Tüm mutasyon yapan API uç noktaları (`companies`, `departments`, `personnel`, `providers`, `flows`, `change_requests`, `git_sync`) için `log_action()` çağrıları eklendi.
- Her oluşturma, güncelleme ve silme işlemi kullanıcı kimliği, şirket kimliği ve işlem detaylarıyla birlikte kaydedilir.
- Denetim günlüğü sayfası: **Ayarlar → Denetim Günlüğü**.

---

## v0.2 — 19 Haziran 2026

### Yeni Özellikler

#### Ajan Belleği
- Ajan oturumları arasında kalıcı bellek desteği eklendi.
- `MemoryStore` modeli: anahtar-değer çiftleri, TTL, şirket ve ajan bazlı kapsam.

#### Akış Araç Kullanımı (Flow Tool Use)
- Otonom akışlar artık araç çağrılarını (tool calls) destekler.
- Araç sonuçları akış geçmişine kaydedilir.

#### Çok Dilli Arayüz
- Tüm sayfalar `t()` çeviri fonksiyonuyla sarmalandı.
- Desteklenen diller: Türkçe, İngilizce.

---

## v0.1 — 1 Haziran 2026

### İlk Yayın (Faz 1 + Faz 2)

#### Temel Platform
- Şirket ve departman yönetimi (CRUD).
- İnsan ve ajan yönetimi.
- Organizasyon şeması görselleştirmesi.
- Kullanıcı rolleri ve davet sistemi (founder, executive, dept_head, agent_owner, user).
- JWT tabanlı kimlik doğrulama.

#### AI Altyapısı
- Provider key yönetimi: Anthropic, OpenAI, Google Gemini, Mistral.
- Ajan çalışma zamanı: araç çağrıları, beceri (skill) sistemi, oturum geçmişi.
- MCP (Model Context Protocol) araç desteği.

#### Entegrasyonlar
- GitHub / GitLab / Gitea entegrasyonu (markdown dosyası senkronizasyonu).
- Resend ile e-posta tabanlı davet sistemi.
- A2A (Agent-to-Agent) delegasyon protokolü.

#### Arayüz
- SvelteKit 5 + Svelte runes mimarisi.
- Özel shadcn/ui esinli bileşen kütüphanesi.
- Çok şirket desteği; sidebar şirket değiştirici.
- Karanlık / Aydınlık tema.
