---
sidebar_position: 1
---

# fab.engineering — Kurumsal Yapay Zeka Katmanı

**Versiyon 1.0** · Self-hosted, açık kaynak (MIT) · [GitHub](https://github.com/fab-agent/agentic-organization)

> **Kurumsal hafıza ve kurumsal yapay zeka ile işleriniz artık çok daha verimli ve hızlı.**

Veritabanı, uygulama (API, MCP) bağlantılarını içeren ekibinizle birlikte çalışacak bir kurumsal yapay zeka katmanı. Süslü değil — çalışan bir arayüz, açık kaynak, model bağımsız.

---

## Temel İlkeler

### Tam Şeffaflık
Sizden gizli çalışan hiçbir katman yok. Kaynak koda bakabilir, yapay zekanıza sorabilir ya da doğrudan terminalden inceleyebilirsiniz. MIT lisansı, şeffaf mimari.

### Model Bağımsızlığı
Claude, GPT-4o, Gemini, Qwen ya da son çıkan herhangi bir model — illa bir modele ya da her zaman son sürüme bağlı değilsiniz. İhtiyacınıza göre değiştirirsiniz.

### Gerçek Bağlantılar
Ajanlarınız sadece sohbet etmez. Mevcut veritabanlarınıza, dahili API'lerinize ve MCP sunucularınıza bağlanır. Gerçek iş süreçlerinin içinde çalışır.

### Kurumsal Hafıza
Şirketinizin bilgisi, deneyimi ve süreçleri yapay zeka eşliğinde korunur ve büyür. Yeni çalışanlar geçmişe anında erişir; ajanlar bağlamı hiç unutmaz.

---

## Temel Kavramlar

| Kavram | Açıklama |
|---|---|
| **Şirket** | En üst organizasyon birimi. Birden fazla şirket yönetilebilir. |
| **Departman** | Şirkete bağlı ekip/birim. Hedefler ve politika listesi taşır. |
| **Personel** | İnsan çalışan veya ajan. Her ikisi de aynı hiyerarşide yer alır. |
| **Ajan** | Bir personele atanmış AI yapılandırması (model + skill + durum). |
| **Skill** | Ajanın sahip olduğu yetenek tanımı (ad, versiyon, açıklama). |
| **Politika** | Şirket, departman veya ajan kapsamında geçerli kural/direktif. |
| **Platform Kullanıcısı** | E-posta + şifreyle giriş yapan insan personel. Davet ile eklenir. |

---

## Neler Yapılabilir?

- Birden fazla şirketi tek platformdan yönet
- `parent_id` ile iç içe departman hiyerarşisi kur; org chart'ta departman görünümünü kullan
- Her personele özgü AI ajan yapılandır
- Anthropic, OpenAI, Google, Mistral veya Qwen modellerinden birini seç — model bağımsız
- Ajan yapılandırma değişikliklerini iki aşamalı onay akışından geçir (Değişiklik Talepleri)
- Departman ve skill filtreyle uygun ajana görev gönder (Görev Talepleri)
- Ajana resim ürettir — Qwen Image, DALL-E ve uyumlu modeller desteklenir
- Ekip üyelerini platforma davet et; rol bazlı erişim kontrolü uygula (5 kademe)
- Arayüzü Türkçe veya İngilizce kullan

---

## Denemeye Başlayın

| | |
|---|---|
| **Demo** | [demo.agent.fab.engineering](https://demo.agent.fab.engineering) — ücretsiz, kayıt gerektirmez |
| **Uygulama** | [app.agent.fab.engineering](https://app.agent.fab.engineering) — kendi hesabınızla giriş yapın |

---

## Self-Hosted Kurulum

```bash
git clone https://github.com/fab-agent/agentic-organization.git
cd agentic-organization
cp .env.example .env
# .env içine JWT_SECRET değerini girin
docker compose up --build
```

Arayüz → [http://localhost:5173](http://localhost:5173)

Detaylı kurulum için → [Kurulum Kılavuzu](./getting-started/installation.md)

---

## Kimlik Doğrulama

Platform, davet tabanlı bir kullanıcı sistemi kullanır. Kullanıcılar sisteme kendi kendine kayıt olamaz; yöneticiler İnsanlar sayfasından e-posta ile davet gönderir. Roller (`founder`, `executive`, `dept_head`, `agent_owner`, `user`) hangi sayfaların görüneceğini ve hangi işlemlerin yapılabileceğini belirler.

Detaylı bilgi için → [Kimlik Doğrulama ve Roller](./platform/auth-and-roles.md)

---

## İletişim

Soru, öneri ya da geri bildirim için:
- **LinkedIn**: [Kuntay Kunt](https://www.linkedin.com/in/kuntaykunt/)
- **X**: [x.com/kuntaykunt](https://x.com/kuntaykunt)
- **E-posta**: bilgi@kuntaykunt.com

Site dili: Türkçe. Yayın adresi: [docs.fab.engineering](https://docs.fab.engineering)
