---
sidebar_position: 1
---

# Kurulum

fab.engineering platformunu üç farklı yöntemle kurabilirsiniz.

---

## Gereksinimler

| Yöntem | Gereksinim |
|---|---|
| Docker (önerilen) | Docker Engine 24+, Docker Compose v2 |
| Manuel | Python 3.11+, Node.js 20+, pip/uv |
| CLI Sihirbazı | Node.js 20+, Docker Compose |

---

## Yöntem 1 — Docker ile (Önerilen)

```bash
git clone https://github.com/fab-agent/3rdparty-agent-org.git
cd 3rdparty-agent-org

cp .env.example .env
# İsterseniz .env içine AI anahtarlarınızı ekleyin (sonradan arayüzden de eklenebilir)

docker compose up --build
```

Kurulum tamamlandığında:

- **Arayüz:** `http://localhost:5173`
- **API:** `http://localhost:8000`
- **API Dokümantasyonu:** `http://localhost:8000/docs`

---

## Yöntem 2 — Manuel (Geliştirme Ortamı)

**Backend:**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend (ayrı terminalde):**

```bash
cd frontend
npm install
cp .env.example .env              # VITE_API_URL=http://localhost:8000
npm run dev
```

Frontend `http://localhost:5173` adresinde açılır.

---

## Yöntem 3 — CLI Sihirbazı (`3pa init`)

CLI sihirbazı ilk kurulumu adım adım yönlendirir.

```bash
cd packages/cli
npm install
npx 3pa init
```

Sihirbaz sırasıyla şunları sorar:

1. **Şirket bilgileri** — Ad ve sektör
2. **AI sağlayıcı** — Anthropic, OpenAI, Google veya Mistral seçimi ve API anahtarı girişi
3. **Git entegrasyonu** — GitHub/GitLab/Gitea bağlantısı (atlanabilir)
4. **Başlatma** — `docker compose up` ile otomatik başlatma

---

## İlk Açılış — Kurulum Sihirbazı

Platform ilk açıldığında veritabanında hiç kullanıcı yoksa otomatik olarak **kurulum sayfasına** yönlendirilirsiniz.

Bu sayfada:

1. **Ad Soyad** — yönetici kullanıcının adı
2. **Şirket Adı** — platformdaki ilk şirket
3. **E-posta** — giriş için kullanılacak adres
4. **Şifre** — en az 8 karakter

Form gönderildiğinde kullanıcı `founder` rolüyle oluşturulur ve otomatik giriş yapılır.

:::info
Kurulum formu yalnızca veritabanı boşken görünür. Bir kullanıcı oluşturulduktan sonra `/setup` sayfası devre dışı kalır.
:::

---

## Ortam Değişkenleri

```bash
# Backend (.env)

# --- Kimlik Doğrulama (Zorunlu) ---
JWT_SECRET=gizli-ve-uzun-rastgele-bir-dize    # JWT imzalama anahtarı — en az 32 karakter
# İlk yönetici hesabı kurulum sihirbazıyla oluşturulur (/setup sayfası)

# --- Bildirim Sistemi ---
APP_URL=http://localhost:5173                 # Frontend adresi (Telegram bildirimlerindeki bağlantılar için)
# Telegram bot ayarları Ayarlar → Entegrasyonlar arayüzünden yapılır, .env gerektirmez

# --- AI Sağlayıcıları (Opsiyonel) ---
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
MISTRAL_API_KEY=...
QWEN_API_KEY=sk-...           # Alibaba DashScope

# Frontend (.env)
VITE_API_URL=http://localhost:8000
```

:::info
AI anahtarları `.env` yerine **Ayarlar → AI Sağlayıcıları** sayfasından da eklenebilir. Arayüzden eklenen anahtarlar şifrelenmiş olarak veritabanında saklanır.
:::

:::caution
`JWT_SECRET` değerini ayarlamadan platformu başlatmayın. `JWT_SECRET`'ın tahmin edilemez ve en az 32 karakter uzunluğunda olduğundan emin olun. İlk yönetici hesabı kurulum sihirbazından oluşturulur; sabit bir şifre tanımlamanıza gerek yoktur.
:::

---

## Telegram Bot Kurulumu

Davet ve şifre sıfırlama bildirimleri Telegram üzerinden iletilir. `.env` ayarı gerekmez; tüm yapılandırma arayüzden yapılır.

1. Telegram'da [@BotFather](https://t.me/BotFather) botuna `/newbot` komutunu gönderin.
2. Bot adı ve kullanıcı adı belirleyin; BotFather size bir **token** verecektir (`123456789:AAF...` formatında).
3. Bildirimlerin gideceği chat'e botunuzu ekleyin veya bota `/start` gönderin.
4. [@userinfobot](https://t.me/userinfobot) ile chat ID'nizi öğrenin (grup için negatif sayı olacaktır).
5. Platformda **Ayarlar → Entegrasyonlar → Telegram Bildirimleri** bölümüne girerek token ve chat ID'yi kaydedin. "Bağlan" butonuna bastığınızda bot doğrulanır.
6. "Test" butonu ile admin chat'e doğrulama mesajı göndererek kurulumu tamamlayın.

---

## Sonraki Adım

Kurulum tamamlandıktan sonra [Kullanım Kılavuzu](./agent-usage.md) sayfasına geçin.  
Kullanıcı rolleri ve davet sistemi için → [Kullanıcı Rolleri](./user-roles.md)
