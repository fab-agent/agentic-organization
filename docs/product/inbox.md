---
id: inbox
title: Gelen Kutusu
sidebar_label: Gelen Kutusu
---

# Gelen Kutusu

Gelen Kutusu, platformun tüm bildirim ve otomasyon sonuçlarının toplandığı merkezi mesajlaşma alanıdır. Otonom akış çıktıları, görev bildirimleri ve sistem mesajları burada listelenir.

---

## Erişim

**Gelen Kutusu** (`/inbox`) sayfasına tüm roller erişebilir. Sol kenar çubuğundaki **Gelen Kutusu** menü öğesiyle açılır.

---

## Mesaj Türleri

| Tür | İkon Rengi | Açıklama |
|---|---|---|
| `flow` (Akış) | Mor | Otonom akış çalışmasının sonucu |
| `task_request` (Görev) | Mavi | Yeni görev ataması bildirimi |
| `task_result` (Sonuç) | Yeşil | Tamamlanan görev çıktısı |
| `system` (Sistem) | Mavi | Platform tarafından üretilen sistem mesajları |

Okunmamış mesajlar, listede mavi nokta ve kalın yazı ile belirtilir. Sağ üstte **yeni** rozeti okunmamış mesaj sayısını gösterir.

---

## Otomatik Yenileme

Gelen Kutusu, **her 30 saniyede bir** arka planda mesajları yeniler. Sayfa açık olduğu sürece yeni bildirimler otomatik olarak görünür; manuel yenileme gerekmez.

---

## Filtreleme ve Arama

Filtre çubukları yardımıyla mesajları zaman aralığına göre daraltabilirsiniz:

| Filtre | Gösterilen |
|---|---|
| **Tümü** | Tüm mesajlar |
| **Bu hafta** | Son 7 gün |
| **Bu ay** | Son 30 gün |

**Sadece yeni** düğmesiyle yalnızca okunmamış mesajları listeleyin.

---

## Mesaj Eylemleri

### Mesajı Aç / Kapat

Bir mesaj satırına tıkladığınızda alt kısımda tam içerik açılır. Mesaj bu tıklamayla otomatik olarak **okundu** olarak işaretlenir.

### Tümünü Okundu İşaretle

Okunmamış mesaj varken başlık alanında görünen **Tümünü Okundu İşaretle** butonu tüm mesajları bir seferde okundu yapar.

### Sil

Her mesajın sağındaki çöp kutusu ikonuyla mesaj kalıcı olarak silinir. Silme işlemi geri alınamaz.

---

## Onayınızı Bekleyen Görevler

Size atanmış ve henüz işlem yapılmamış görev talepleri, mesaj listesinin üzerinde ayrı bir bölümde sarı arka planla vurgulanır.

Her bekleyen görev kartında:

- **Görev başlığı ve açıklaması**
- **Not alanı** — isteğe bağlı; çalıştırma veya reddetme gerekçesi
- **Çalıştır** — Görevi LLM API ile çalıştırır; sonuç talebi oluşturan kişinin Gelen Kutusu'na düşer
- **Reddet** — Görevi reddeder; talebi oluşturan kişiye bildirim gider

Görev Talepleri hakkında ayrıntılı bilgi için → [Görev Talepleri](./task-requests.md)

---

## Görev Talebi Oluşturma

Başlık alanındaki **Görev Talebi** butonu, yeni bir görev talebi formunu açar. Form doğrudan Gelen Kutusu sayfasındayken kullanılabilir. Detaylar için → [Görev Talepleri](./task-requests.md)

---

## API Endpoint'leri

| Endpoint | Yöntem | Açıklama | İzin |
|---|---|---|---|
| `/inbox?company_id=` | GET | Mesaj listesi (filtreli) | `user+` |
| `/inbox/{id}/read` | POST | Mesajı okundu işaretle | Mesaj sahibi |
| `/inbox/read-all?company_id=` | POST | Tümünü okundu yap | `user+` |
| `/inbox/{id}` | DELETE | Mesaj sil | Mesaj sahibi |
