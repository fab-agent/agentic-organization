---
sidebar_position: 3
---

# Kişiler ve Erişim

Kimse platforma kendi kendine kayıt olamaz. Her kullanıcı, bir yönetici tarafından davet edilir.

## Davet etme

1. **Yapı → İnsanlar**'da kişinin kaydını açın (türü **İnsan** olmalı) ve **E-posta** alanını doldurun. E-postası olup davet edilmemiş kişiler **Davet edilmedi** etiketiyle görünür.
2. Satırdaki zarf simgesine basın, bir **platform rolü** seçin ve **Davet Gönder**'e basın.
3. Sistem, `XXXXX-XXXXX` biçiminde **30 dakika geçerli** bir geçici şifre üretir, kullanıcı hesabını ve şirket üyeliğini oluşturur ve şifreyi kişiye gönderir. Satır **Aktif** olur.

Gönderim e-posta ile (Resend yapılandırılmışsa) ve Telegram ile (şirket için bot tanımlıysa) yapılır. İkisi de yoksa mesaj yalnızca sunucu günlüğüne yazılır; bu durumda geçici şifreyi oradan almanız gerekir.

## İlk giriş

Kişi `/login` sayfasında e-posta ve geçici şifreyle girer; sistem onu otomatik olarak **yeni şifre belirleme** sayfasına yönlendirir. Süre dolmuşsa girmeye çalıştığında yeni bir geçici şifre üretilip gönderilir.

## Şifre unutulursa

Kendi kendine sıfırlama yoktur ve arayüzde bir "şifre sıfırla" düğmesi bulunmaz. İki yol var:

- Geçici şifrenin süresi dolmuşsa, kullanıcı giriş yapmayı denediğinde sistem **otomatik olarak yeni bir geçici şifre üretip gönderir**.
- Bir yönetici API üzerinden `POST /auth/reset/{user_id}` çağırarak yeni geçici şifre gönderebilir.

Giriş yapmış bir kullanıcı kendi şifresini **Profil** sayfasından değiştirebilir (en az 8 karakter). Profil sayfası ayrıca üyesi olduğunuz şirketleri ve her birindeki rolünüzü gösterir.

## Roller

Rol, **şirket başına** verilir (bir kişi farklı şirketlerde farklı rolde olabilir). Beş rol vardır:

| Rol | Kısaca | Kenar çubuğunda gördükleri |
|---|---|---|
| **Kurucu** `founder` | Tam yetki; şirketi silebilir; kullanıcıları ve Telegram'ı yönetir | Hepsi |
| **Yönetici** `executive` | Kurucuya yakın; Ayarlar'a erişir; değişiklik taleplerinde son onayı verir | Hepsi |
| **Bölüm yöneticisi** `dept_head` | Yapıyı yönetir; değişiklik taleplerinin ilk onayını verir | Panel, Yapı, Organizasyon, Değişiklikler, Akışlar, İşler, Delegasyon |
| **Ajan sorumlusu** `agent_owner` | Sorumlu olduğu ajanlar ve akışlarla çalışır | Panel, Akışlar, İşler, Delegasyon |
| **Kullanıcı** `user` | Günlük çalışma: sohbet, görev talebi, delegasyon | Panel, İşler, Delegasyon (+ girişte Gelen Kutusu) |

Karşılaştırma:

| İşlem | Kullanıcı | Ajan sorumlusu | Bölüm yön. | Yönetici | Kurucu |
|---|:---:|:---:|:---:|:---:|:---:|
| Sohbet, görev talebi, delegasyon | ✓ | ✓ | ✓ | ✓ | ✓ |
| Akış oluşturma | | ✓ | ✓ | ✓ | ✓ |
| Yapı, organizasyon, davet | | | ✓ | ✓ | ✓ |
| Değişiklik talebi — ilk onay | | | ✓ | ✓ | ✓ |
| Değişiklik talebi — son onay | | | | ✓ | ✓ |
| Ayarlar (sağlayıcılar, Git, yedek, veritabanı…) | | | | ✓ | ✓ |
| Telegram ayarları, kullanıcı yönetimi, şirketi silme | | | | | ✓ |

:::caution Arayüz ile API arasındaki fark
Yukarıdaki tablo **arayüzde** görünen ve yapılabilen şeyleri anlatır. API tarafında departman, personel, akış gibi işlemler yalnızca şirket üyeliğini kontrol eder; rol kontrolü şu işlemlerde API'de de vardır: şirket bilgilerini güncelleme (yönetici+), şirketi silme (kurucu), kullanıcı yönetimi ve Telegram (kurucu), sağlayıcı anahtarları, politika/yetenek/yedek/veritabanı yazma işlemleri (bir şirkette en az bölüm yöneticisi olmak). Hassas bir kurulumda API'ye doğrudan erişimi kısıtlayın. Bkz. [Güvenlik](/technical/security).
:::

## Rol değiştirme

Bir kişinin rolü, davet edilirken verilir. Değiştirmek için bir yönetici kişiyi aynı e-postayla yeni rolle yeniden davet eder (mevcut üyelik güncellenir) veya kurucu üyeliği düzenler.
