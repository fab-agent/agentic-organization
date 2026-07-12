---
sidebar_position: 0
---

# Changelog

Platform güncellemelerinin kronolojik kaydı.

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
