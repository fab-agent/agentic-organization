---
sidebar_position: 2
---

# Organizasyon: Şirket, Departman, Personel

## Şirketler

Bir kurulumda birden fazla şirket olabilir; her birinin departman, personel, ajan ve politika verisi bağımsızdır. Sol alttaki şirket kutusundan şirketler arasında geçiş yapar, **Şirket Ekle** ile yenisini oluşturursunuz. Şirket bilgilerini (ad, sektör, web sitesi, vizyon, misyon, değerler, hedefler) **Panel** sayfasından düzenlersiniz; bu bilgiler ajanların bağlamına da girer.

## Departmanlar

**Yapı → Bölümler**. Departmanlar bir ağaç oluşturur: her departman en fazla bir üst departmana bağlanır.

| Alan | Açıklama |
|---|---|
| Ad | Zorunlu. Örnek: `Yazılım Geliştirme` |
| Slug | Kısa ad; addan otomatik üretilir, elle düzenlenebilir |
| Üst departman | Boş bırakırsanız kök departman olur |
| Açıklama | Departmanın sorumluluğu |
| Hedefler | Her satır bir hedef (OKR) |
| Politikalar | Bu departmandaki ajanlara uygulanacak politikalar |
| Durum | Aktif / Pasif |

Kurallar: bir departman kendisini üst birim seçemez; döngü oluşturacak seçimler listeden dışlanır. Departman silinirse alt birimleri silinmez, kök departmana dönüşür.

Departmana bağlanan politikalar, o departmandaki ajanların varsayılan politikaları olur ([Yetenekler ve Politikalar](/guide/skills-and-policies)).

## Personel

**Yapı → İnsanlar**. Personel hem insanları hem ajanları kapsar; ikisi aynı hiyerarşide yer alır.

| Alan | Zorunlu | Açıklama |
|---|---|---|
| Ad soyad | Evet | |
| Slug | Evet | Otomatik üretilir |
| Ünvan | Hayır | Görünen pozisyon |
| Rol | Hayır | Serbest rol etiketi (platform rolü değildir) |
| Tür | Evet | **İnsan** veya **Ajan** |
| Departman | Hayır | |
| Yönetici | Hayır | Raporlama hiyerarşisi |
| E-posta | Hayır | İnsan personel için; platform davetinde kullanılır |

Platform erişimi vermek için [davet](/guide/people-and-access) gerekir. Ajan türünde bir kayıt eklenince ajan yapılandırması otomatik açılır → [Ajanlar](/guide/agents).

Personel silinirse kalıcı olarak kaldırılır; ajanlar için **arşivleme** (pasif yapma) kaydı korur.

## Organizasyon şeması

**Organizasyon** sayfası iki görünüm sunar:

- **Personel:** her kişiyi ve ajanı hiyerarşik bir ağaçta gösterir. İnsanlar ve ajanlar farklı renktedir; bir ajan kartına tıklayınca model, yetenekler, durum ve sorumlusu görünür. Yakınlaştırma/uzaklaştırma ve sıfırlama düğmeleri vardır.
- **Departman:** departmanları ağaç olarak listeler; kökler daraltılıp genişletilir, her birimin yanında insan ve ajan sayısı görünür.
