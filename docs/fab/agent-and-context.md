---
sidebar_position: 3
---

# Kişinin Ajanı ve Prompt

## Kişi başına tek görünür ajan (ADR-0019)

- Her insan personelin tam olarak bir ajan personası vardır (`type = agent`, tek `AgentConfig`, `responsible_id` = insan). Çalışma alanıyla birlikte oluşturulur.
- Ajan arka plan görevleri ve alt ajanlar başlatabilir; alt ajanlar başka alt ajanları çağırabilir (derinlik, eşzamanlılık ve bütçe sınırı politikayla). Bunlar **personel değil, çalıştırmadır** (run).
- Kenar çubuğu **ajanları değil işi** gösterir: güncel ve son oturumlar/çalıştırmalar ve durumları.
- **Yetki büyümez.** Alt ajanın yetkisi ebeveyninin alt kümesidir; her çalıştırma, ebeveyninden türetilen ve yalnızca daralabilen kısa ömürlü bir token alır. Politika motoru her araç çağrısında yine karar verir.
- Her denetim olayı `person`, `session`, `run_id`, `parent_run_id` ve serbest metin `role` taşır; ajan dallansa da çalıştırma ağacı yeniden kurulabilir.

## "Alanım"

Tek tuşla açılan kalıcı görünüm: şirket bağlamı (vizyon, misyon, değerler, hedefler), departman hedefleri, kişinin rolü ve iş tanımı (`Personnel.job_description`), geçerli politikalar sade dille ve **ajanın neyi neden yapmayacağı**. Bir istek reddedilirse veya onaya düşerse yanıt hangi kuralın olduğunu söyler ve "değişiklik öner" seçeneği sunar.

## Katmanlı bağlam

Düşük öncelikten yükseğe: temel kurallar → politikalar (şirket ∪ departman ∪ kişi ∪ ajan) → şirket → departman → kişinin işi → ajanın öğrendikleri. Politikalar kazanır; ajan yalnızca kısıt ekleyebilir.

**Kendi kendine öğrenme görünür ve tek yönlüdür:** yalnızca kişinin kendi mesaj ve düzeltmelerinden öğrenilir (araç sonuçlarından, belgelerden veya web içeriğinden asla), öğrenilenler sürümlü ve denetlenebilirdir, tek tuşla geri alınır.

## Token bütçeli prompt (ADR-0020)

Prompt, adlı ve sayılmış bölümlerden (`Section`) birleşir. Bütçe `PROMPT_BUDGET_TOKENS` (varsayılan 2000, başlangıç değeri). Bütçe aşılırsa isteğe bağlı bölümler sabit sırayla düşer: `knowledge`, `memory`, `department`, `job`, `company`. `identity`, `rules`, `closing` asla düşmez.

- **Sabit önce, tur başına değişen sona:** sağlayıcının prompt önbelleği uzun ortak öneki kullanabilsin.
- Politikalar prompt'ta yalnızca **isim** olarak yer alır (en çok 20). Asıl uygulama araç çağrısı anında yapılır; ayrıntıyı dışarıda bırakmak yararlılığa mal olur, güvenliğe değil.
- Token sayıları **tahmindir** (tokenizer yok); büyümeyi izlemek içindir, faturalama için değil.
- Her gerçek prompt bölüm adı ve boyutlarını günlüğe yazar (`prompt_assembled`); metin asla yazılmaz.

## Niyet sınıflandırma (TypeSafe Jev)

Kullanıcının **ilk mesajı** görev türü, şirket bilgisi gerekip gerekmediği, hassasiyet ve (departmanlar varsa) alan bakımından sınıflandırılır. Sonuç prompt'u yalnızca **daraltır**; ör. sohbet dışı bir selam tüm isteğe bağlı bölümleri düşürür. Aynı kayıt iş incelemesi için etiket olur.

Kısıtlar (hepsi testli):

- **Asla güvenlik denetimi değildir.** Niyet bölüm ekleyemez, yetkiyi genişletemez.
- **Hızlı ve hataya açık.** 1,5 sn zaman aşımı, yeniden deneme yok; herhangi bir hata "niyet yok" demektir, yani tam prompt.
- **Maliyet kapısı.** Çağrı başına ~520 giriş token'ı. Yalnızca yeterince büyük prompt'larda (`INTENT_MIN_PROMPT_TOKENS`, varsayılan 1500) çalışır.
- **Yalnızca oturumun ilk turu;** sonraki turlarda önek değişip önbelleği bozmasın ve "tamam" gibi devam mesajları sohbet sayılmasın.
- **Denetimde metinsiz:** `intent_classified` olayı etiketleri, atlanan bölümleri ve token sayılarını yazar; mesajı asla.
- **Şirket dışına çıkar,** bu yüzden varsayılan kapalıdır: `TYPESAFE_API_KEY` **ve** AppConfig `intent.enabled` birlikte gerekir.

Gerçek Jev ile ölçüm (29 Eylül 2026): yanlış kırpılan gerçek iş 0/48, p50 0,24 sn. Yerel bir yedek sınıflandırıcı yoktur; Jev olmadan sonuç tam prompt'tur.
