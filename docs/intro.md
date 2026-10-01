---
sidebar_position: 1
slug: /
---

# fab.engineering

**Şirketinizin yapay zeka ajanlarını organizasyon şemasına yerleştirin, yönetin ve denetleyin.**

fab.engineering, kendi sunucunuzda çalışan, açık kaynaklı bir platformdur. Her ajanın bir adı, rolü, departmanı ve sorumlu bir insanı vardır; ajanlar şirket yapısında diğer çalışanlar gibi yer alır. Politikalar, onay akışları ve denetim kaydı baştan gelir.

## Kimin için, nereden başlamalı?

| Siz kimsiniz? | Önce şuraya bakın |
|---|---|
| **Şirket yöneticisi / kurucu** — ne işe yaradığını ve nasıl kurulacağını öğrenmek istiyorum | [İlk Adımlar](/getting-started/first-steps) → [AI ile Kurulum](/guide/onboarding) |
| **Departman çalışanı** — ajanla çalışacağım | [Ajanla Sohbet](/guide/chat), [Görev Talepleri ve Gelen Kutusu](/guide/tasks-and-inbox) |
| **Departman yöneticisi** — ekibimin ajanlarını ve onayları yönetiyorum | [Ajanlar](/guide/agents), [Değişiklik Talepleri](/guide/change-requests) |
| **BT / kurulum sorumlusu** | [Gereksinimler](/getting-started/requirements), [Kurulum](/getting-started/installation), [Ayarlar](/guide/settings) |
| **Geliştirici** — kendi bilgisayarımda opencode ile çalışacağım | [Geliştirici İş İstasyonu](/workstation/overview) |
| **Departman çalışanı, terminalde çalışmak istiyorum** | [fab terminal istemcisi](/fab/overview) |
| **Platformu geliştiren / inceleyen** | [Teknik Bölüm](/technical/architecture), [Geliştirici Notları](/developer-notes/overview) |

## Üç çalışma yüzeyi

Aynı sunucu, aynı politikalar, aynı denetim kaydı; kişinin işine göre üç farklı kapı:

| Yüzey | Kimin için | Durum |
|---|---|---|
| **Web arayüzü** | Herkes: sohbet, akışlar, onaylar, yönetim | Kullanıma hazır |
| **Geliştirici iş istasyonu** (`3pa` + opencode) | Yazılım geliştiriciler | Kullanıma hazır |
| **`fab` terminal istemcisi** | Finans, muhasebe, satış gibi departmanlar | Geliştirme aşamasında: gerçek çalışma alanı çalışma zamanı henüz yok, bkz. [fab](/fab/overview) |

## Temel kavramlar

| Kavram | Anlamı |
|---|---|
| **Şirket** | En üst birim. Bir kurulumda birden fazla şirket yönetilebilir; veriler birbirinden ayrıdır. |
| **Departman** | Şirketin bir birimi. Üst departmana bağlanabilir; hedefleri ve politikaları vardır. |
| **Personel** | Organizasyon şemasındaki bir kişi. Türü **insan** veya **ajan** olabilir. |
| **Ajan** | Bir yapay zeka modeli (ör. Claude, GPT, Gemini), yetenekleri ve politikalarıyla bir personele bağlanmış çalışma birimi. Her ajanın sorumlu bir insanı vardır. |
| **Yetenek (skill)** | Ajanın kullanabildiği araç: web arama, grafik üretimi, veritabanı sorgusu, harici API gibi. |
| **Politika** | Şirket, departman veya ajan için geçerli yazılı kural. |
| **Platform kullanıcısı** | E-posta ve şifreyle giriş yapan kişi. Davet ile eklenir; rolü neleri görebileceğini belirler. |

## Temel ilkeler

- **Kendi sunucunuzda.** Veriler sizde kalır; yapay zeka modeli sağlayıcılarına yalnızca sizin tanımladığınız anahtarlarla bağlanılır.
- **Modelden bağımsız.** Anthropic, OpenAI, Google, Mistral, Qwen, yerel modeller (Ollama, LM Studio) ve OpenAI uyumlu her adres kullanılabilir.
- **İnsan onayı.** Ajan yapılandırması değişiklikleri iki aşamalı onaydan geçer; ajanlar arası görev devri insan onayı ister.
- **İzlenebilirlik.** Önemli işlemler denetim kaydına yazılır. Geliştirici iş istasyonu katmanında kayıt ayrıca değiştirilemez bir hash zinciridir.
- **Açık kaynak.** Kaynak kodu [GitHub](https://github.com/fab-agent/agentic-organization) üzerinde; lisans için depodaki `LICENSE` dosyasına bakın.

## Kendi sunucunuzda deneyin

Kurulum için [Kurulum](/getting-started/installation) sayfasına, ardından [İlk Adımlar](/getting-started/first-steps) sayfasına geçin.

## İletişim

[LinkedIn](https://www.linkedin.com/in/kuntaykunt/) · [X](https://x.com/kuntaykunt) · bilgi@kuntaykunt.com
