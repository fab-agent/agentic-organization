---
sidebar_position: 3
---

# İlk Adımlar

Kurulum bittikten sonra, bir şirketi çalışır hâle getirmek için bu sırayı izleyin. Her adım ilgili kılavuz sayfasına bağlanır.

## 1. Giriş yapın

[Kurulum sihirbazında](/getting-started/installation#i̇lk-açılış) oluşturduğunuz hesapla giriş yapın. Bu hesap **kurucu** rolündedir ve her şeye erişir.

## 2. Bir yapay zeka sağlayıcısı ekleyin

**Ayarlar → AI Sağlayıcıları**'ndan en az bir sağlayıcının anahtarını girin ve **Kaydet & Test Et**'e basın. Anahtar şifrelenerek saklanır. Bu adım olmadan ajanlar yanıt veremez. Ayrıntı: [Ayarlar](/guide/settings#ai-sağlayıcıları).

## 3. Organizasyonu kurun

İki yol var:

- **Hızlı yol:** **Ayarlar → AI ile Kur**. Sistem şirketiniz hakkında web araştırması yapar, size 3–5 soru sorar ve departmanları, kişileri, ajanları, yetenekleri ve politikaları tek seferde önerir. Siz önizlemeyi onaylarsınız. → [AI ile Kurulum](/guide/onboarding)
- **Elle:** Departmanları, kişileri ve ajanları teker teker ekleyin. → [Organizasyon](/guide/organization), [Ajanlar](/guide/agents)

## 4. Ekibi davet edin

**Yapı → İnsanlar** sayfasında kişinin e-postasını ekleyip davet gönderin ve bir rol seçin. Kişi geçici şifreyle girer, ilk girişte yeni şifre belirler. → [Kişiler ve Erişim](/guide/people-and-access)

## 5. Bir ajanla konuşun

**İşler** sayfasında bir ajan seçip yeni sohbet başlatın. → [Ajanla Sohbet](/guide/chat)

## 6. İşi otomatikleştirin

Tekrarlayan bir görev için **Akışlar** sayfasında zamanlanmış bir akış kurun; sonuç ilgili kişinin Gelen Kutusu'na düşer. → [Otonom Akışlar](/guide/flows), [Görev Talepleri ve Gelen Kutusu](/guide/tasks-and-inbox)

## Arayüz haritası

Sol kenar çubuğunda görünen bölümler, kişinin rolüne göre değişir:

| Bölüm | Adres | Kimler görür |
|---|---|---|
| **Panel** | `/` | Herkes |
| **Yapı** (Bölümler · İnsanlar · Ajanlar · Yetenekler · Politikalar) | `/departments` ve kardeşleri | Bölüm yöneticisi ve üstü |
| **Organizasyon** | `/org-chart` | Bölüm yöneticisi ve üstü |
| **Değişiklikler** | `/change-requests` | Bölüm yöneticisi ve üstü |
| **Akışlar** | `/flows` | Ajan sorumlusu ve üstü |
| **İşler** (sohbet) | `/chat` | Herkes |
| **Delegasyon** | `/a2a` | Herkes |
| **Ayarlar** | `/settings` | Yönetici ve üstü |

**Gelen Kutusu** (`/inbox`) kenar çubuğunda bağlantı olarak yer almaz. `Kullanıcı` rolündeki kişiler girişte doğrudan buraya yönlendirilir, diğerleri adresi tarayıcıdan açar. **Ajanlar** sayfası ise `Ajan sorumlusu` rolünde girişte açılır ve Yapı sekmeleri içinden de ulaşılır.

:::info Roller arayüzde nasıl uygulanır?
Yukarıdaki görünürlük, arayüzün menüyü role göre göstermesidir. Sunucu (API) tarafında bütün işlemler için şirket üyeliği zorunludur; bazıları ayrıca rol ister (şirket ayarı, kullanıcı yönetimi, sağlayıcı anahtarları gibi). Ayrıntı: [Kişiler ve Erişim → Roller](/guide/people-and-access#roller) ve [Güvenlik](/technical/security).
:::

## Dil ve tema

Sağ üstteki seçiciden **Türkçe** veya **English** seçilir. Başka dil yoktur.
