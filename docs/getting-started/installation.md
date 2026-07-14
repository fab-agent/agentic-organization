---
sidebar_position: 1
---

# Kurulum

fab.engineering platformunu üç farklı yöntemle kurabilirsiniz.

---

## Geliştirme Ortamı — Hızlı Başlangıç

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

## Prodüksiyon Kurulumu (Tek Komut)

Sunucunuza bağlandıktan sonra tek bir komutla prodüksiyona alabilirsiniz:

```bash
curl -fsSL https://raw.githubusercontent.com/fab-agent/3rdparty-agent-org/main/install.sh | bash
```

Ya da repoyu indirip çalıştırın:

```bash
git clone https://github.com/fab-agent/3rdparty-agent-org.git
cd 3rdparty-agent-org
bash install.sh
```

`install.sh` sırasıyla şunları yapar:

1. Docker ve Docker Compose kurulumu kontrol eder
2. `.env` sihirbazı (`setup-env.sh`) ile yapılandırma oluşturur
3. Let's Encrypt üzerinden SSL sertifikası alır (Certbot)
4. Nginx yapılandırmasını domain ile üretir
5. Tüm servisleri `docker compose -f docker-compose.prod.yml up -d` ile başlatır
6. Sağlık kontrolü yapar

### .env Sihirbazı

Sadece ortam değişkenlerini yapılandırmak için:

```bash
bash setup-env.sh
```

Sihirbaz şunları sorar:

1. **Alan adı** — ör. `agents.sirketim.com`
2. **Şirket bilgileri** — ad, sektör
3. **Güvenlik anahtarları** — `JWT_SECRET` ve `ENCRYPTION_KEY` otomatik oluşturulur
4. **AI sağlayıcı anahtarları** — isteğe bağlı, arayüzden de eklenebilir
5. **E-posta bildirimleri** — gönderici adresi
6. **Güncelleme bildirimleri** — isteğe bağlı kayıt (MIT lisanslı, ücret yok)

---

## Manuel Kurulum (Geliştirme Ortamı)

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

# ── Zorunlu ────────────────────────────────────────────────────────────────────
DOMAIN=agents.sirketim.com           # Prodüksiyon domain'i
JWT_SECRET=<en az 32 karakter>       # JWT imzalama anahtarı
ENCRYPTION_KEY=<en az 32 karakter>   # Sağlayıcı anahtar şifreleme

# ── Şirket ─────────────────────────────────────────────────────────────────────
COMPANY_NAME=Şirket Adı
COMPANY_SECTOR=Yazılım
APP_URL=https://agents.sirketim.com

# ── Bildirim ───────────────────────────────────────────────────────────────────
EMAIL_FROM=noreply@sirketim.com

# ── AI Sağlayıcıları (Opsiyonel) ──────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
MISTRAL_API_KEY=...
QWEN_API_KEY=sk-...
```

:::info
AI anahtarları `.env` yerine **Ayarlar → AI Sağlayıcıları** sayfasından da eklenebilir. Arayüzden eklenen anahtarlar şifrelenmiş olarak veritabanında saklanır.
:::

:::caution
`JWT_SECRET` ve `ENCRYPTION_KEY` değerlerini ayarlamadan prodüksiyon ortamında çalıştırmayın. `setup-env.sh` bu değerleri `openssl rand -hex 32` ile otomatik üretir.
:::

---

## SSL Sertifikası (Manuel)

`install.sh` SSL'i otomatik yapılandırır. Manuel olarak yapmak isterseniz:

```bash
# Sertifika al (port 80 serbest olmalı)
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /var/www/certbot:/var/www/certbot \
  -p 80:80 \
  certbot/certbot certonly \
    --standalone \
    --email admin@sirketim.com \
    --agree-tos \
    -d agents.sirketim.com

# nginx.conf üret
sed 's/__DOMAIN__/agents.sirketim.com/g' nginx.prod.conf.template > nginx.conf

# Başlat
docker compose -f docker-compose.prod.yml up -d
```

Sertifika yenileme (`certbot renew`) için bir cron job eklemeniz önerilir:

```bash
# /etc/cron.d/certbot-renew
0 0 * * 0 root certbot renew --quiet && docker exec 3rdparty-nginx nginx -s reload
```

---

## Telegram Bot Kurulumu

Davet ve şifre sıfırlama bildirimleri Telegram üzerinden iletilir. `.env` ayarı gerekmez; tüm yapılandırma arayüzden yapılır.

1. Telegram'da [@BotFather](https://t.me/BotFather) botuna `/newbot` komutunu gönderin.
2. Bot adı ve kullanıcı adı belirleyin; BotFather size bir **token** verecektir (`123456789:AAF...` formatında).
3. Bildirimlerin gideceği chat'e botunuzu ekleyin veya bota `/start` gönderin.
4. [@userinfobot](https://t.me/userinfobot) ile chat ID'nizi öğrenin.
5. Platformda **Ayarlar → Entegrasyonlar → Telegram Bildirimleri** bölümüne girerek token ve chat ID'yi kaydedin.

---

## Sonraki Adım

Kurulum tamamlandıktan sonra [Kullanım Kılavuzu](./agent-usage.md) sayfasına geçin.  
Kullanıcı rolleri ve davet sistemi için → [Kullanıcı Rolleri](./user-roles.md)
