---
sidebar_position: 2
---

# Kullanım Kılavuzu

Platform kurulumu tamamlandıktan sonra bu kılavuz ile temel iş akışlarını öğrenebilirsiniz.

---

## Arayüze Genel Bakış

Sol kenar çubukta sekiz ana bölüm bulunur:

| Bölüm | Adres | Açıklama |
|---|---|---|
| Yapı | `/` | Özet istatistikler |
| Bölümler | `/departments` | Departman yönetimi |
| İnsanlar | `/personnel` | Personel listesi |
| Ajanlar | `/agents` | Ajan yönetimi |
| Organizasyon | `/org-chart` | Hiyerarşik ağaç görünümü |
| İşler | `/chat` | Ajanlarla sohbet |
| Delegasyon | `/a2a` | Ajanlar arası görev devri |
| Ayarlar | `/settings` | AI sağlayıcılar + Git |

---

## Şirket Yönetimi

Kenar çubuğun altında aktif şirket görüntülenir.  
Şirket kutusuna tıklandığında açılan menüden:

- Mevcut şirketler arasında geçiş yapılabilir
- **"Şirket Ekle"** ile yeni şirket oluşturulabilir

Her şirket bağımsız departman, personel ve ajan verisi taşır.

---

## Tipik İş Akışı

### Adım 1 — Şirket Oluştur (veya var olanı seç)

Kenar çubukta şirket adına tıkla → **"Şirket Ekle"** → Şirket adı gir → **"Ekle"**

---

### Adım 2 — Departman Ekle

**Departmanlar** sayfasına git → **"Yeni Departman"** butonuna bas.

Gerekli alanlar:
- **Ad** ve **Slug** (otomatik oluşturulur)
- **Açıklama** — Departmanın rolü
- **Hedefler** — Satır satır OKR/hedef tanımları
- **Politikalar** — Departmana bağlı kural listesi (örn. "Code Review SLA")

---

### Adım 3 — Personel Ekle

**Personel** sayfasına git → **"Yeni Personel"** butonuna bas.

| Alan | Zorunlu | Açıklama |
|---|---|---|
| Ad Soyad | ✅ | |
| Slug | ✅ | Otomatik oluşturulur |
| Ünvan | — | Görüntülenen pozisyon |
| Rol | — | Sistem rolü |
| Tür | ✅ | **İnsan** veya **Ajan** |
| Departman | — | Atanacak departman |
| Yönetici | — | Raporlama hiyerarşisi |

---

### Adım 4 — Ajan Yapılandır

Personel türü **"Ajan"** olarak eklendikten sonra `AgentConfig` otomatik oluşturulur.  
API üzerinden (`PATCH /personnel/{id}/agent-config`) veya yakında gelecek detay sayfasından:

- **Model** seçilir: `claude-sonnet-4-6`, `gpt-4o`, `gemini-2.5-pro`, vb.
- **Durum** belirlenir: `draft` → `active` → `inactive`
- **Sorumlu kişi** atanır (hangi insan bu ajanı denetler?)
- **Skill** eklenir: ad, versiyon, kısa açıklama

Skill örnekleri:
```
Code Review    v2.1   PR inceleme ve güvenlik taraması
SEO            v1.4   Anahtar kelime araştırması
Forecasting    v1.2   Nakit akışı tahmini
```

---

### Adım 5 — Org Haritasını İncele

**Org Haritası** sayfası aktif şirketin tüm personelini hiyerarşik ağaçta gösterir.

- 🟦 **İnsan** düğümleri mavi
- 🤖 **Ajan** düğümleri turuncu

Bir ajan düğümüne tıklandığında sağ panelde model, skill listesi, durum ve sorumlu kişi görüntülenir.

---

## AI Sağlayıcı Kurulumu

**Ayarlar → AI Sağlayıcıları** sayfasında dört sağlayıcı için API anahtarı eklenebilir.

1. İlgili sağlayıcının kutusuna API anahtarını gir
2. **"Kaydet"** butonuna bas — anahtar şifrelenerek saklanır
3. **"Test Et"** butonu ile anahtarın geçerliliği doğrulanır

Durum göstergeleri:
- 🟢 **Aktif** — Anahtar geçerli
- 🔴 **Geçersiz** — Anahtar hatalı veya süresi dolmuş
- ⚪ **Yapılandırılmamış** — Henüz anahtar girilmemiş

---

## Git Entegrasyonu

**Ayarlar → Git Entegrasyonu** sekmesinde veritabanını bir Git reposuna bağlayabilirsiniz.

### Bağlantı Kurma

1. **Sağlayıcı** seçin: GitHub / GitLab / Gitea
2. **Repo URL** girin: `https://github.com/sirketiniz/agents.git`
3. **Branch** girin (varsayılan: `main`)
4. **Access Token** girin:
   - GitHub: `ghp_...`
   - GitLab: `glpat-...`
5. **"Bağlan"** butonuna basın

### Senkronizasyon

| İşlem | Açıklama |
|---|---|
| **Pull** | Repodaki YAML dosyalarını veritabanına aktarır |
| **Push** | Veritabanını YAML'a çevirir, commit + push eder |
| **Otomatik PR** | Push yerine pull request oluşturur (ekip onayı için) |

### YAML Formatı

Reponuzda oluşturulan dosya örneği:

```yaml
# agents/codeguard/agent.yaml
id: codeguard
name: CodeGuard
title: Code Review Agent
model: claude-sonnet-4-6
model_version: '4.6'
status: active
department: yazilim-gelistirme
responsible: elif-yildiz
skills:
  - name: Code Review
    version: '2.1'
    description: PR inceleme ve güvenlik taraması
updated_at: '2026-06-01'
```

---

## Dil Değiştirme

Sağ üst köşede **dil seçici** butonu bulunur.  
Desteklenen diller: 🇹🇷 Türkçe · 🇬🇧 English · 🇩🇪 Deutsch · 🇪🇸 Español

---

## API ile Doğrudan Çalışma

Platform çalışırken interaktif API dokümantasyonu:

```
http://localhost:8000/docs      ← Swagger UI
http://localhost:8000/redoc     ← ReDoc
```

Sık kullanılan endpoint örnekleri:

```bash
# Tüm şirketleri listele
curl http://localhost:8000/companies

# Belirli şirketin departmanları
curl "http://localhost:8000/departments?company_id=<id>"

# Ajan skill ekle
curl -X POST http://localhost:8000/personnel/<id>/skills \
  -H "Content-Type: application/json" \
  -d '{"name": "Data Analysis", "version": "1.0", "description": "..."}'
```
