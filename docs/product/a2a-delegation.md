---
sidebar_position: 4
---

# Ajan-Ajana (A2A) Delegasyon

Bir ajan konuşma sırasında yapamadığı bir işi başka bir ajana devredebilir. Bu mekanizma **Ajan-Ajana Delegasyon** (A2A) olarak adlandırılır.

---

## Ne Zaman Kullanılır?

| Senaryo | Delegasyon Akışı |
|---|---|
| InstaCraft görsel üretemez | InstaCraft → PostMediaAgent |
| LinkMind kod yazamaz | LinkMind → CodeGuard |
| SupportBot finans sorusunu yanıtlayamaz | SupportBot → LedgerAI |
| Herhangi bir ajan → özel uzmanlık gerektiren iş | İstekçi Ajan → Uzman Ajan |

---

## Nasıl Çalışır?

```
Kullanıcı → İstekçi Ajan
               │
               ├─ [delegate_to_agent aracını çağırır]
               │    to_agent_slug: "postmediaagent"
               │    task: "LinkedIn kapak görseli üret"
               │    context: "Mavi tonlar, modern stil..."
               │
               ▼
         A2A Talebi oluşturulur (pending_approval)
               │
               ▼
         Sorumlu kişiye bildirim → Telegram /onaylar veya A2A sayfası
               │
               ├─ ✅ Onaylarsa → Hedef Ajan çalışır
               │                   │
               │                   ▼
               │             Sonuç → pending_result_approval
               │                   │
               │                   ▼
               │             İkinci onay (sonucu kabul et)
               │                   │
               │                   ▼
               │             Sonuç İstekçi Ajan'a döner
               │
               └─ ❌ Reddederse → Talep iptal edilir
```

---

## Kurulum — Adım Adım

### 1. Hangi ajanlara skill eklenmeli?

`delegate_to_agent` yeteneklerini yalnızca **delegasyon başlatacak** ajanlara eklemek gerekir.  
Delegasyonu *alan* ajan (PostMediaAgent gibi) bu skill'e ihtiyaç duymaz.

**Örnek:** InstaCraft görsel işini PostMediaAgent'a devredecekse → skill yalnızca InstaCraft'a eklenir.

---

### 2. Skill'i UI'dan Ekleme

**Ajanlar** sayfasına gidin → ilgili ajanı seçin → **Yetenek Ekle** butonuna tıklayın:

```
Ad:        delegate_to_agent          (tam bu isim olmalı)
Versiyon:  1.0
Açıklama:  Yapamadığın işleri başka bir ajana delege et
Tür:       Dahili
Fonksiyon: Ajan Delegasyonu
```

> **Önemli:** Ad alanı `delegate_to_agent` olmalıdır (boşluk değil alt çizgi). Sistem bu isimle eşleştirir.

---

### 3. Hedef Ajan Slug'larını Öğrenme

Ajan slug'larını **Personel** sayfasında ya da ajan profilinde görebilirsiniz. Örnek slug'lar:

| Ajan Adı | Slug |
|---|---|
| PostMediaAgent | `postmediaagent` |
| CodeGuard | `codeguard` |
| LedgerAI | `ledgerai` |
| LinkMind | `linkmind` |

Slug'lar küçük harf, boşuksuz formattadır. Sistemde ajan oluşturulurken otomatik belirlenir.

---

### 4. Ajana Kimlerle Çalışabileceğini Öğretmek (İsteğe Bağlı)

Ajan hangi slug'lara delege edebileceğini sistem prompt'u veya politika üzerinden öğrenebilir.  
**Politika Ekle → Kapsam: Ajan** yoluyla şuna benzer bir kural tanımlayabilirsiniz:

```markdown
# Delegasyon Politikası

## Görev Yönlendirme
- Görsel üretim talepleri → `postmediaagent`
- Kod inceleme talepleri → `codeguard`
- Finans soruları → `ledgerai`

## Kural
Yapamadığın işleri yukarıdaki ajanlara delege et.
Delegasyon için `delegate_to_agent` aracını kullan.
```

---

## Gerçek Senaryo: InstaCraft → PostMediaAgent

**Kullanıcı mesajı:**
> "Fabrika Yazılım için bir LinkedIn kapak görseli lazım."

**InstaCraft'ın iç çağrısı** (kullanıcı görmez):
```json
{
  "tool": "delegate_to_agent",
  "to_agent_slug": "postmediaagent",
  "task": "Fabrika Yazılım için profesyonel bir LinkedIn kapak görseli oluştur.",
  "context": "Modern, mavi tonlar. Şirket adı görünür olsun."
}
```

**InstaCraft'ın kullanıcıya yanıtı:**
> "Görsel üretimi için PostMediaAgent'a talep oluşturdum. Onayınızı bekliyorum."

**Siz:** Telegram'dan `/onaylar` → **✅ Onayla** butonuna basın  
**Sonuç:** PostMediaAgent görsel üretir, sonuç A2A sayfasında görünür.

---

## A2A Durumları

| Durum | Anlamı |
|---|---|
| `pending_approval` | İlk onay bekleniyor |
| `approved` | Onaylandı, hedef ajan çalışmaya başlıyor |
| `running` | Hedef ajan görevi yürütüyor |
| `pending_result_approval` | Sonuç onayı bekleniyor |
| `completed` | Tüm süreç tamamlandı |
| `rejected` | Reddedildi |

---

## Telegram Entegrasyonu

Yeni bir delegasyon talebi oluştuğunda **@fablimitedBot** üzerinden `/onaylar` komutunu kullanabilirsiniz:

```
/onaylar

📋 Bekleyen Onaylar

🤝 [A2A] LinkedIn kapak görseli
  [✅ Onayla]  [❌ Reddet]
```

Butona basmanız yeterli — ayrıca sisteme girmenize gerek yok.

---

## Sık Sorulan Sorular

**Tüm ajanlara otomatik eklense olmaz mıydı?**  
Hayır. Her ajan her işi delege edebiliyorsa kontrol kaybedilir. Hangi ajan kime delege edebilir — bunu bilinçli olarak kurgulamak iyi bir governans pratiğidir.

**Ajan yanlış ajana mı delege etti?**  
Onay aşamasında reddedebilirsiniz. Red gerekçesini yazabilirsiniz, gelecekte ajan bu bilgiyi öğrenir (hafıza ile).

**Onay olmadan çalışabilir mi?**  
Şu an hayır — tüm A2A talepleri onay gerektirir. Bu kasıtlı bir tasarım kararıdır: ajan özerkliği arttıkça insan denetimi korunur.

**Sonuç onayı da mı gerekiyor?**  
Evet, iki aşamalı: görevi onaylarsınız → ajan çalışır → sonucu onaylarsınız. İkinci onayda sonucu görebilir, yetersizse reddedebilirsiniz.
