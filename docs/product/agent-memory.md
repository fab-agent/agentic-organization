---
sidebar_position: 13
---

# Ajan Belleği

Ajanlar varsayılan olarak stateless'tır — her sohbet oturumu sıfırdan başlar. **Ajan Belleği** özelliği, kapanan oturumlardan otomatik özetler üretir ve bu özetleri bir sonraki oturumda sistem promptuna ekler.

---

## Nasıl Çalışır?

```
Oturum kapanır
    ↓
Arka plan görevi tetiklenir
    ↓
LLM, konuşmayı özetler (max 100 kelime)
    ↓
AgentMemory tablosuna yazılır
    ↓
Yeni oturum açılır
    ↓
Son 3 özet sistem promptuna inject edilir
```

---

## Özet Üretimi

Oturum kapatıldığında (`DELETE /sessions/{id}`) arka planda otomatik bir LLM çağrısı yapılır:

- Konuşmanın son 30 mesajı alınır
- LLM şunu üretir: *"In a previous session, ..."* formatında kısa bir özet
- Özet `AgentMemory` tablosuna kaydedilir
- Özet üretme başarısız olsa bile oturum kapatma etkilenmez

---

## Sistem Promptuna Enjeksiyon

Yeni bir sohbet oturumu başladığında, ajanın son 3 belleği sistem promptunun sonuna eklenir:

```
Context from your previous sessions:
  - In a previous session, the user asked about the Q1 budget report.
    The agent completed the analysis and delivered a summary to the inbox.
  - In a previous session, the agent helped onboard a new team member
    named Elif by explaining department policies.
```

---

## Yapılandırma

Şu an bellek enjeksiyonu tüm ajanlar için otomatik olarak aktiftir. Gerekli tek koşul: platformda en az bir aktif AI sağlayıcı anahtarı bulunmalıdır.

| Parametre | Değer |
|---|---|
| Özetlenen maks. mesaj | 30 |
| Inject edilen önceki oturum sayısı | 3 |
| Maks. özet uzunluğu | ~100 kelime |

---

## Veri Modeli

```sql
AgentMemory
  id           UUID primary key
  personnel_id UUID → Personnel
  session_id   UUID → AgentSession (nullable)
  summary      TEXT
  created_at   DATETIME
```

---

## Sınırlamalar

- Mevcut yapı **metin tabanlı özetleme** kullanır; vektör arama veya semantik geri çağırma yoktur.
- Özetler LLM tarafından üretildiğinden, çok kısa oturumlar (< 2 mesaj) için bellek oluşturulmaz.
- Bellek özetleri düzenlenemez; fazla gürültü oluşması durumunda doğrudan veritabanından silinebilir.
