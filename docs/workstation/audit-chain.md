---
sidebar_position: 4
---

# Değiştirilemez Denetim Zinciri

> ADR-0006 · `backend/services/audit_chain.py`, `backend/services/audit_anchor.py`

[Audit Log](/product/audit-log) her mutasyonu kaydeder ama satırları
teknik olarak düzenlenebilir. Yürütme katmanı, ajan eylemleri için
**hash-zincirli**, kanıtlanabilir bir kayıt ekler: bir satır silinir veya
değiştirilirse zincir doğrulaması bunu ortaya çıkarır.

---

## Zincir yapısı

Her kiracı (şirket) için ayrı bir zincir tutulur. `AuditEvent` satırı:

| Alan | Açıklama |
|---|---|
| `chain_key` | Kiracı zinciri anahtarı |
| `seq` | Zincir içi sıra numarası (0'dan artan) |
| `action` | `gateway_call` · `policy_decision` · `tool_event` · `sandbox_start` … |
| `payload_json` | Olay ayrıntısı (untrusted içerik olarak ele alınır) |
| `prev_hash` | Bir önceki olayın hash'i |
| `hash` | `sha256(prev_hash + canonical(payload) + seq + …)` |

İlk olayın `prev_hash`'i sabit bir genesis değeridir. Her yeni olay bir öncekine
kriptografik olarak bağlıdır — araya ekleme, silme veya değiştirme zinciri
kırar.

---

## Yazma yolu

gateway çağrısı, politika kararı ve araç olayı tek bir `record()` fonksiyonundan
geçer. `record()`:

1. Zincire yeni `AuditEvent` ekler (Postgres'te advisory lock ile — eşzamanlı
   yazımlar sırayı bozmaz).
2. Geriye dönük uyumluluk için eski `AuditLog` tablosuna da bir ayna satır yazar.

---

## Doğrulama

| Endpoint | Açıklama |
|---|---|
| `GET /audit/chain/verify` | Bir kiracının zincirini baştan sona yeniden hash'leyip bütünlüğü kontrol eder |
| `GET /workstation/audit/verify` | Aynısının persona-kapsamlı hâli (`3pa audit verify` bunu çağırır) |

`verify_all()` tüm kiracı zincirlerini kontrol eder; bir APScheduler işi bunu
periyodik çalıştırır.

---

## Harici çıpalama

Sunucuyu ele geçiren biri hem zinciri hem doğrulamayı yeniden yazabilir. Buna
karşı `services/audit_anchor.py` periyodik olarak zincir **başlıklarını**
(chain_key, son seq, son hash) platform dışına yazar:

| Hedef | Nasıl |
|---|---|
| Yerel `jsonl` | Append-only dosya, ayrı diskte/dizinde |
| S3 Object Lock | **COMPLIANCE** modda kova — nesne, saklama süresi dolana dek root tarafından bile silinemez/değiştirilemez |

`check_anchors()` mevcut zinciri son çıpayla karşılaştırır; başlık geriye
gitmişse veya hash uyuşmuyorsa **kesme / yeniden yazma** tespiti verir.

| Endpoint | Açıklama |
|---|---|
| `GET /audit/chain/anchors` | Kayıtlı çıpaları listeler |
| `POST /audit/chain/anchors` | Şimdi bir çıpa al (normalde zamanlanmış iş yapar) |

Yapılandırma `AppConfig` içinde: çıpa aralığı, S3 kova/prefix/retention.

---

## Önem skorlaması

Denetim zinciri *bütünlüğü* kanıtlar, *önemi* değil. Hangi olayın bakmaya değer
olduğunu **LLM önem skorlaması** (ADR-0013, `services/audit_severity.py`)
belirler: 10 dakikada bir çalışan bir iş, ilginç olayları bir modele
sınıflandırtır (risk 1–5 + kategori + gerekçe), yüksek puanlıları sorumlu insana
`InboxMessage` ve şirketin Telegram admin sohbetine uyarı olarak iletir. Skor,
zincire değil `AuditSeverity` yan tablosuna yazılır — zincir hiç değişmez.
`severity.autopolicy` açıkken, bir şirket bir saat içinde eşik sayıda
yüksek-önem olay biriktirirse politika modu otomatik `enforce`'a çekilir.
