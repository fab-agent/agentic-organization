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

## İlk Açılış

Platform ilk açılışta örnek veri yükler:

| Şirket | Departman | İnsan | Ajan |
|---|---|---|---|
| Fabrika Yazılım | 6 | 10 | 9 |
| Demo Corp | 1 | 2 | 1 |

Bu verileri şablon olarak kullanabilir ya da silebilirsiniz.

---

## Ortam Değişkenleri

```bash
# Backend (.env)

# --- Kimlik Doğrulama (Zorunlu) ---
JWT_SECRET=gizli-ve-uzun-rastgele-bir-dize    # JWT imzalama anahtarı — en az 32 karakter
FOUNDER_EMAIL=kurucu@sirket.com               # İlk açılışta otomatik oluşturulan kurucu hesabı
FOUNDER_PASSWORD=ilk-giris-sifresi            # Kurucu'nun başlangıç şifresi (ilk girişte değiştirin)

# --- E-posta / Davet Sistemi (Zorunlu) ---
RESEND_API_KEY=re_...                         # Resend.com API anahtarı (davet e-postaları için)
EMAIL_FROM=noreply@fab.limited               # Gönderen e-posta adresi
APP_URL=http://localhost:5173                 # Frontend adresi (e-postalardaki bağlantılar için)

# --- AI Sağlayıcıları (Opsiyonel) ---
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
MISTRAL_API_KEY=...

# Frontend (.env)
VITE_API_URL=http://localhost:8000
```

:::info
AI anahtarları `.env` yerine **Ayarlar → AI Sağlayıcıları** sayfasından da eklenebilir. Arayüzden eklenen anahtarlar şifrelenmiş olarak veritabanında saklanır.
:::

:::caution
`JWT_SECRET`, `RESEND_API_KEY` ve `FOUNDER_EMAIL`/`FOUNDER_PASSWORD` değerlerini ayarlamadan platformu başlatmayın. JWT_SECRET'ın tahmin edilemez ve yeterince uzun olduğundan emin olun. `FOUNDER_PASSWORD` ile ilk girişi yaptıktan sonra **hemen şifrenizi değiştirin**.
:::

---

## Resend Kurulumu

Davet e-postaları [Resend](https://resend.com) üzerinden gönderilir.

1. [resend.com](https://resend.com) adresinden ücretsiz hesap açın.
2. **API Keys** bölümünden yeni bir anahtar oluşturun.
3. Anahtarı `RESEND_API_KEY` değişkenine yapıştırın.
4. `EMAIL_FROM` alanına Resend'de doğruladığınız bir domain'e ait e-posta adresini girin (örn. `noreply@sirketiniz.com`). Domain doğrulaması yapmak istemiyorsanız `noreply@fab.limited` ile başlayabilirsiniz.

---

## Sonraki Adım

Kurulum tamamlandıktan sonra [Kullanım Kılavuzu](./agent-usage.md) sayfasına geçin.  
Kullanıcı rolleri ve davet sistemi için → [Kullanıcı Rolleri](./user-roles.md)
