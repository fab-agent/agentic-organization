---
sidebar_position: 4
---

# Ajanlar

Ajan, bir yapay zeka modelinin yetenekleri ve politikalarıyla bir personele bağlanmış hâlidir. Her ajanın **sorumlu bir insanı** vardır; ajanın çıktıları ve onay talepleri o kişiye gelir.

**Nerede:** **Yapı → Ajanlar**.

## Ajan oluşturma

**Yeni Ajan** düğmesi şu bilgileri ister:

| Bölüm | Alan | Açıklama |
|---|---|---|
| Temel bilgiler | Ajan adı, slug, ünvan/rol, durum | Slug, ajanlar arası görev devrinde ajanın adresi olarak kullanılır |
| Model ve bağlantılar | **LLM modeli** | Anahtarı tanımlı sağlayıcıların modelleri listelenir. Anahtarı olmayan bir model seçilirse sohbette uyarı çıkar |
| | **Sorumlu çalışan** | Ajanı denetleyen insan |
| | **Departman** | Seçince o departmanın politikaları otomatik eklenir |
| İş tanımı | Serbest metin | **Skill Öner** düğmesi, iş tanımını analiz edip uygun yetenekleri önerir |
| Yetenekler | Kütüphaneden seç / araç ekle | Bkz. [Yetenekler ve Politikalar](/guide/skills-and-policies) |
| Politikalar | Departman politikaları + ek politikalar | |

Ajan, kayıt sırasında bir personel kaydı (**tür: ajan**) ve bir ajan yapılandırması olarak oluşur; organizasyon şemasında diğer çalışanlar gibi görünür.

## Durumlar

| Durum | Anlamı |
|---|---|
| **Taslak** (`draft`) | Hazırlanıyor, henüz kullanıma açılmadı |
| **Aktif** (`active`) | Kullanıma hazır; sohbette seçilebilir, akış ve görev yönlendirmesinde yer alır |
| **Arşivlenmiş** (`inactive`) | Listeden gizlenir; kayıt ve geçmiş korunur |

**Arşivle** kaydı korur; **Sil** kalıcıdır. Geçmişi saklamak istiyorsanız arşivleyin.

## Değişikliği onaya göndermek

Bir ajanın yapılandırmasını doğrudan değiştirmek yerine satırdaki **Değişiklik Talebi** düğmesiyle (türü: ajan yapılandırması, yetenek veya politika) bir talep açabilirsiniz. Talep iki aşamalı onaydan geçer, onaylanınca uygulanır ve istenirse Git'e yazılır. → [Değişiklik Talepleri](/guide/change-requests)

## Ajanın hafızası

Bir sohbet kapandığında sistem o oturumun özetini çıkarır ve ajanın **uzun dönem hafızasına** ekler; sonraki oturumlarda bu özetler bağlam olarak kullanılır. Ayrıntı: [Ajanla Sohbet → Hafıza](/guide/chat#hafıza).
