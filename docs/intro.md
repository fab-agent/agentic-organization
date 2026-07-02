---
sidebar_position: 1
---

# fab.engineering

**Self-hosted, açık kaynak** — şirketlerin yapay zeka ajanlarını organize biçimde yönetmesini sağlayan platform.

Her personele AI ajan tanımlanır, politika ve yetenekler YAML dosyaları üzerinden yönetilir, organizasyon şeması görselleştirilir. Platform, davet tabanlı kullanıcı sistemi ve rol hiyerarşisiyle ekip bazlı erişim kontrolü sunar.

---

## Temel Kavramlar

| Kavram | Açıklama |
|---|---|
| **Şirket** | En üst organizasyon birimi. Birden fazla şirket yönetilebilir. |
| **Departman** | Şirkete bağlı ekip/birim. Hedefler ve politika listesi taşır. |
| **Personel** | İnsan çalışan veya ajan. Her ikisi de aynı hiyerarşide yer alır. |
| **Ajan** | Bir personele atanmış AI yapılandırması (model + skill + durum). |
| **Skill** | Ajanın sahip olduğu yetenek tanımı (ad, versiyon, açıklama). |
| **Platform Kullanıcısı** | E-posta + şifreyle giriş yapan insan personel. Davet ile eklenir. |

---

## Neler Yapılabilir?

- Birden fazla şirketi tek platformdan yönet
- `parent_id` ile iç içe departman hiyerarşisi kur; org chart'ta departman görünümünü kullan
- Her personele özgü AI ajan yapılandır
- Anthropic, OpenAI, Google veya Mistral modellerinden birini seç
- Ajan yapılandırma değişikliklerini iki aşamalı onay akışından geçir (Değişiklik Talepleri)
- Onaylanan değişiklikleri GitHub'a otomatik commit et (GitHub Entegrasyonu)
- Cron zamanlayıcısıyla ajanları otomatik çalıştır (Otonom Akışlar)
- Departman ve skill filtreyle uygun ajana görev gönder (Görev Talepleri)
- Akış sonuçları ve görev bildirimlerini Gelen Kutusu'ndan takip et (30s polling)
- Ekip üyelerini e-posta ile platforma davet et; rol bazlı erişim kontrolü uygula
- Arayüzü Türkçe veya İngilizce kullan

---

## Hızlı Başlangıç

```bash
git clone https://github.com/fab-agent/3rdparty-agent-org.git
cd 3rdparty-agent-org
cp .env.example .env
# .env içine JWT_SECRET ve RESEND_API_KEY değerlerini girin
docker compose up --build
```

Arayüz → [http://localhost:5173](http://localhost:5173)

Detaylı kurulum için → [Kurulum Kılavuzu](./getting-started/installation.md)

---

## Kimlik Doğrulama

Platform, davet tabanlı bir kullanıcı sistemi kullanır. Kullanıcılar sisteme kendi kendine kayıt olamaz; yöneticiler İnsanlar sayfasından e-posta ile davet gönderir. Roller (`founder`, `executive`, `dept_head`, `agent_owner`, `user`) hangi sayfaların görüneceğini ve hangi işlemlerin yapılabileceğini belirler.

Detaylı bilgi için → [Kimlik Doğrulama ve Roller](./platform/auth-and-roles.md)

---

Site dili: Türkçe. Yayın adresi: [docs.fab.engineering](https://docs.fab.engineering)
