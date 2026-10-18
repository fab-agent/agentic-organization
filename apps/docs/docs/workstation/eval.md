---
sidebar_position: 10
---

# Değerlendirme ve Hata Atfı

> ADR-0023 · `backend/services/run_diagnosis.py`, `backend/services/run_reader.py`, `backend/api/eval.py`

Bir ajan çalışması kötü giderse sorulacak soru "hangi katmanı düzeltmeliyim?"dir: model mi, prompt mu, araç mı, politika mı. Ayrı bir değerlendirme deposu yoktur; kayıt kaynağı [denetim zinciridir](/workstation/audit-chain). Teşhis o kayıtları okur.

## Şu an çalışan: çalışma teşhisi (aşama 1)

Bir çalışmanın (`run_id`) denetim olayları birlikte okunur ve katmanlara göre **bulgu** üretilir:

| Katman | Örnek bulgu |
|---|---|
| `model` | Sağlayıcı hatası, boş çıktı |
| `prompt` | Token bütçesi yüzünden atılan bölümler (niyet gereği atlananlar hata sayılmaz) |
| `tool` | Araç hatası, aynı aracın tekrar tekrar hata vermesi |
| `policy` | Reddedilen veya onay isteyen karar ve eşleşen kural |

Sonuç bir **şüpheli katman**dır; katmanlar eşitse hiçbiri seçilmez. Bunlar **sinyaldir, kanıt değildir**: nereye bakılacağını söyler.

Güven kuralları:

- Mesaj ve belge metni okunmaz; adlar yalnızca kısa tanımlayıcıya benziyorsa gösterilir (anahtar, e-posta, UUID biçimleri gösterilmez). Bu bir anonimleştirme değildir.
- İş istasyonundan gelen olaylara sunucu `origin: client` damgası vurur. İstemcinin sunucu gözlemi gibi sunduğu olaylar (gateway, politika, bağlam) yok sayılır ve sayılır.
- Kuru çalıştırma (dry-run) kararları puan getirmez; fail-closed karar ayrı bir yapılandırma hatasıdır.
- Girdi 5000 olayla sınırlıdır; kesilirse sonuçta `truncated` yazar. Bozuk olaylar sayılır, işlemi durdurmaz.

## API

| Uç | Ne yapar |
|---|---|
| `GET /eval/personas/{id}/runs` | Kayıtlı teşhisleri listeler |
| `GET /eval/personas/{id}/runs/{run}` | Tek teşhisi döner |
| `POST /eval/personas/{id}/runs/{run}/diagnose` | Teşhisi hesaplar veya (son 10 sn içindeyse) kayıtlıyı döner |

Erişim: kurucu; şirket genelindeki yönetici ve bölüm yöneticisi; yalnızca kendi bölümü için kapsamlı yönetici; sorumlu kişi; ajan sahibi. Yetkisiz, bilinmeyen veya bozuk `run_id` aynı `404`'ü döner ve hiçbir şey yazılmaz. Kişi silinince teşhisleri de silinir.

## Henüz yok

- **Yargıçlar** (TypeSafe `Noul`/`Choice` ile başarı ölçümü, kalibrasyonlu): planlandı.
- **Görüntüleme sayfası:** yok; yalnızca API.
- **Tekrar oynatma (replay):** şüpheyi doğrulamak için tek katmanı değiştirip yeniden çalıştırma; probe ortamı gerekir, yok.
- Guardrail ve veri katmanları olay üretmediği için "sinyal yok" görünür.
- Gateway hataları (zaman aşımı, bağlantı, çözümlenemeyen yanıt, kesilen akış) ve boş çıktı/`length` bitişi `gateway_call` olayında kayıtlıdır ve `model` katmanına bulgu olur; istemcinin bağlantıyı kapatması gösterilir ama puanlanmaz.
- `origin` damgasından önceki istemci olayları sunucu olaylarından ayırt edilemez.
