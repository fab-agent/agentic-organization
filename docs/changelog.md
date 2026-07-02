---
sidebar_position: 0
---

# Changelog

Platform güncellemelerinin kronolojik kaydı.

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
