---
sidebar_position: 6
---

# Ajanla Sohbet (İşler)

**İşler** sayfası, ajanlarla konuştuğunuz yerdir. Sol panelde ajan listesi ve geçmiş oturumlar, ortada sohbet, istenirse sağda ajan bilgisi bulunur.

## Sohbet başlatma

1. Sol panelden bir ajan seçin. Şirketteki ajanlar listelenir; anahtarı tanımlı olmayan bir model kullanan ajanda uyarı görürsünüz. Taslak veya arşivlenmiş bir ajanla sohbet etmek yerine ajanı önce **aktif** yapmanız önerilir.
2. **Yeni Sohbet**'e basın ve mesajınızı yazın. `Enter` gönderir, `Shift+Enter` yeni satır açar.
3. Yanıt, yazıldıkça akar. **Durdur** ile kesebilirsiniz.

Ajan, tanımlı yeteneklerini (web arama, veritabanı sorgusu vb.) gerektikçe kendisi çağırır; çağrılar sohbet içinde görünür.

## Dosya eklemek

Ataç düğmesiyle **PDF, metin (TXT), CSV veya görsel** ekleyebilirsiniz. Dosya içeriği ajana bağlam olarak verilir.

## Yanıtların görünümü

Yanıtlar Markdown olarak çizilir: başlıklar, tablolar, listeler, renkli kod blokları. Ayrıca:

- **JSON** otomatik biçimlendirilir.
- **HTML** blokları için kaynağın yanında katlanabilir bir önizleme bulunur.
- **Mermaid** kod blokları diyagrama dönüşür.

## Arka planda çalışan işler

Ajan uzun süren bir iş başlatırsa (ör. başka bir ajana görev devri) "Ajan arka planda çalışıyor" bildirimi görünür; sonuç hazır olunca sohbete düşer.

## Oturumlar

Her sohbet bir **oturum**dur. Geçmiş oturumlar sol panelde listelenir ve açılıp devam edilebilir. Aktif şirketi değiştirirseniz liste o şirketin ajanlarına göre yenilenir.

## Hafıza

Bir oturum kapatıldığında (en az iki mesaj varsa) sistem otomatik bir **özet** çıkarır ve ajanın uzun dönem hafızasına kaydeder. Sonraki oturumlarda bu özetler ajana bağlam olarak verilir; ajan önceki konuşmaları "hatırlar". Hafıza özetlerini **Panel**'de ve personel kaydında görebilirsiniz.

PostgreSQL kurulumlarında geçmiş oturumlar ve özetler ayrıca **anlamsal arama** için indekslenir (pgvector); ajan, ilgili geçmiş bilgiyi bu yolla da bulabilir.

## Ajan bilgi paneli

Sağ üstteki bilgi düğmesi, ajanın departmanını, yöneticisini ve araç/yeteneklerini (pasif olanlar işaretli) gösterir.
