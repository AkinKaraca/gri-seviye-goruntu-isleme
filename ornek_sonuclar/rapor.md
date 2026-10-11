# Gri seviye görüntü işleme sonuçları

Kaynak: Sentetik test görüntüsü; seed=42. Boyut: 2048 × 2048 piksel.

## 1. 8-bit → 6-bit nicemleme

`Q = I // 4` dönüşümü 0–255 değerlerini 0–63 kodlarına indirger. Her dört ardışık giriş değeri aynı koda dönüşür. `6bit_kodlar.png` bu kodları 8-bit PNG içinde saklar; fiziksel olarak 6-bit paketlenmiş bir dosya değildir. Görsel karşılaştırma için `round(Q × 255 / 63)` kullanılır. Bu işlem 64 seviyeyi 0–255 aralığına yayar; kaybolan ayrıntıyı geri getirmez.

## 2. Dört parçada parlaklık

Orijinal görüntü sol üst, sağ üst, sol alt ve sağ alt olarak bölünür. Sırasıyla −60, −20, +20 ve +60 eklenir: `J = clip(I + b, 0, 255)`. İşlem öncesinde int16 dönüşümü yapılarak uint8 taşması engellenir. Tek thread aynı dört parçayı sırayla, dört thread eşzamanlı görevler olarak işler. Ayrı çıktı bölgelerine yazıldığından yazma çakışması yoktur. Tek boyutların artan satır/sütunları alt/sağ parçada kalır.

## 3. Süre karşılaştırması

| İşlem | 1 thread (ms) | 4 thread (ms) | Kazanım: T1 − T4 (ms) | Hızlanma: T1 / T4 |
|---|---:|---:|---:|---:|
| parlaklik | 21.821 | 10.009 | 11.811 | 2.18× |
| histogram | 35.114 | 22.052 | 13.061 | 1.59× |

Her değer 3 ısınma turundan sonra 31 ölçümün medyanıdır. Koşum sırası dönüşümlüdür. Disk okuma/yazma, grafik üretimi, havuzun ilk kuruluşu ve çıktı tamponlarının ayrılması süreye dahil değildir. Görev gönderme, bekleme, hesap içi geçici diziler ve histogramların birleştirilmesi dahildir. Bu, kurulmuş bir thread havuzunda işlem süresini ölçer; programın toplam açılış süresi değildir. Her iki sürüm de aynı dört parça üzerinde aynı işi yapar.

Python `ThreadPoolExecutor` gerçek işletim sistemi thread'leri kullanır. Yoğun hesaplar NumPy'nin yerel kodunda çalışır; saf Python piksel döngüsü kullanılmaz. Dört thread'in dört kat hızlanması beklenmemelidir: görev maliyeti, bellek bant genişliği, görüntü boyutu ve sistem yükü sonucu etkiler. 1'in altındaki hızlanma oranı dört thread'in daha yavaş olduğunu gösterir. Sonuçlar bu çalıştırmaya aittir.

## 4. Paralel histogram

Her parça için 256 kutulu bir yerel histogram `bincount` ile hesaplanır. Ana histogram `H[k] = H₀[k] + H₁[k] + H₂[k] + H₃[k]` ile oluşturulur. Ortak bir sayacı değiştirmek yerine yerel diziler toplanır. Histogramlar orijinal 8-bit görüntü üzerinde hesaplanır. Tek thread de aynı yerel histogramları sırayla üretip toplar.

Doğrulama: tek/dört thread histogramları ve doğrudan tüm görüntü histogramı birebir eşittir. Histogram toplamı 4194304 pikseldir. Parlaklık çıktıları da birebir eşittir.

## 5. 0.75 ile çarpma ve 20 ekleme

`A = floor(0.75 × I)` ve `B = floor(0.75 × I + 20)` uygulanır. Giriş 0–255 olduğundan sonuçlar sırasıyla 0–191 ve 20–211 sınırları içindedir; kırpma gerekmez. Her piksel için `B − A = 20` olur. +20 eklenmesi ortalamayı 20 artırır; standart sapmayı ve maksimum-minimum farkını değiştirmez. 0.75 çarpanı ise girişin parlaklık aralığını daraltır. Görseller aynı 0–255 ölçeğinde gösterildiğinden otomatik kontrast yanıltması yoktur.

| Görüntü | Minimum | Maksimum | Ortalama | Standart sapma |
|---|---:|---:|---:|---:|
| orijinal | 0 | 249 | 111.866 | 61.631 |
| 075_carpim | 0 | 186 | 83.528 | 46.219 |
| 075_carpim_20_ekleme | 20 | 206 | 103.528 | 46.219 |

![Görsel karşılaştırma](gorsel_karsilastirma.png)

![Histogramlar](histogramlar.png)
