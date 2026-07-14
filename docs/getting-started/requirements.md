---
sidebar_position: 0
---

# Sistem Gereksinimleri

fab.engineering'i kendi sunucunuzda çalıştırmak için aşağıdaki gereksinimleri karşılamanız gerekir.

---

## Önerilen Sunucu

| Özellik    | Minimum          | Önerilen         |
|------------|------------------|------------------|
| CPU        | 2 vCPU           | 4 vCPU           |
| RAM        | 4 GB             | 8 GB             |
| Disk       | 20 GB SSD        | 50 GB SSD        |
| İşletim Sistemi | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| Ağ bağlantısı | 100 Mbps    | 1 Gbps           |

:::tip
Hetzner CX33 (4 vCPU, 8 GB RAM, 80 GB SSD, ~13 USD/ay) veya benzeri bulut VPS'ler ideal başlangıç noktasıdır.
:::

---

## Yazılım Gereksinimleri

### Docker ile Kurulum (Önerilen)

| Yazılım | Minimum Sürüm | Notlar |
|---------|---------------|--------|
| Docker Engine | 24.0+ | [Kurulum kılavuzu](https://docs.docker.com/engine/install/) |
| Docker Compose | v2.20+ | Docker Engine 24 ile birlikte gelir |
| `openssl` veya `python3` | herhangi | JWT_SECRET üretmek için |

```bash
# Sürüm kontrolü
docker --version          # Docker version 24.x.x
docker compose version    # Docker Compose version v2.x.x
```

### Manuel Kurulum (Geliştirme Ortamı)

| Yazılım | Minimum Sürüm |
|---------|---------------|
| Python  | 3.11+         |
| Node.js | 20+           |
| pip     | 23+           |
| npm     | 9+            |

---

## Ağ Gereksinimleri

### Açık Portlar

| Port | Protokol | Kullanım |
|------|----------|---------|
| 80   | TCP      | HTTP (Let's Encrypt doğrulaması + HTTPS yönlendirme) |
| 443  | TCP      | HTTPS (prodüksiyon) |

:::info
Geliştirme ortamında 8000 (backend) ve 5173 (frontend) portları localhost'ta açık olur. Prodüksiyonda yalnızca 80 ve 443 dışarıya açık olmalıdır.
:::

---

## Alan Adı (Domain)

Prodüksiyon kurulumu için:

- Yönlendirilmiş bir **alan adı veya alt alan adı** gerekmektedir (ör. `agents.sirketim.com`)
- DNS A kaydının sunucu IP'sine **kurulumdan önce** yönlendirilmesi gerekir
- Let's Encrypt sertifika alımı sırasında domain doğrulaması yapılır
- **Wildcard sertifikası desteklenmez** — tek domain kullanılır

### DNS Kaydı Örneği

```
agents.sirketim.com.  A  1.2.3.4   (sunucu IP'niz)
```

DNS değişikliklerinin yayılması **5 dakika ile 48 saat** arasında sürebilir. Kurulumu başlatmadan önce `nslookup agents.sirketim.com` ile doğrulayın.

---

## Veritabanı

Platform **SQLite** kullanır — harici veritabanı kurulumu gerekmez.

- Veriler `data/app.db` dosyasında saklanır
- Tek sunucu, tek tenant için yeterlidir
- Yüksek eşzamanlılık senaryolarında (100+ eş zamanlı kullanıcı) PostgreSQL'e geçiş değerlendirilebilir
- Yedekleme için `data/` dizinini periyodik olarak yedekleyin (Ayarlar → Yedekleme arayüzü mevcuttur)

---

## AI Sağlayıcıları

Platform AI modeli çalıştırmaz — harici AI sağlayıcı API'larına bağlanır:

| Sağlayıcı    | Ücretsiz Katman | Notlar |
|-------------|-----------------|--------|
| Anthropic   | Hayır           | Claude modelleri |
| OpenAI      | Hayır           | GPT modelleri |
| Google      | Evet (sınırlı)  | Gemini modelleri |
| Mistral     | Evet (sınırlı)  | Mistral modelleri |
| Qwen (Alibaba) | Evet (sınırlı) | DashScope API |
| Ollama      | Ücretsiz        | Yerel model — sunucu üzerinde çalışır |
| LM Studio   | Ücretsiz        | Yerel model — geliştirici makinesinde |

AI anahtarları kurulum sihirbazında veya **Ayarlar → AI Sağlayıcıları** sayfasından eklenebilir.

---

## Güvenlik Notları

- `JWT_SECRET` ve `ENCRYPTION_KEY` değerleri en az 32 karakter olmalıdır
- `data/` dizinine dışarıdan erişim olmamalıdır
- Nginx varsayılan olarak rate limiting uygular (giriş: 5 istek/dakika, API: 60 istek/dakika)
- Sunucu güvenlik duvarında yalnızca 80, 443 ve SSH portları açık olmalıdır

```bash
# UFW ile temel güvenlik duvarı
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```
