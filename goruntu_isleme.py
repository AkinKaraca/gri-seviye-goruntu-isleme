import argparse
import json
import platform
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import perf_counter_ns

import numpy as np
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def test_image(size):
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) / (size - 1)
    a = 20 + 180*x + 25*np.sin(12*np.pi*y) + 12*np.cos(18*np.pi*x)
    a[(x-.32)**2 + (y-.35)**2 < .13**2] = 225
    a[(x > .57) & (x < .85) & (y > .57) & (y < .82)] = 55
    a += np.random.default_rng(42).normal(0, 3, a.shape)
    return np.clip(np.rint(a), 0, 255).astype(np.uint8)


def quadrants(a):
    h, w = a.shape
    return [a[:h//2, :w//2], a[:h//2, w//2:],
            a[h//2:, :w//2], a[h//2:, w//2:]]


def brightness(src, dst, offset):

    dst[:] = np.clip(src.astype(np.int16) + offset, 0, 255)


def histogram(src):
    return np.bincount(src.ravel(), minlength=256)


def benchmark(serial, parallel, repeats):
    for _ in range(3):
        serial()
        parallel()
    samples = {'1_thread': [], '4_thread': []}

    for i in range(repeats):
        jobs = [('1_thread', serial), ('4_thread', parallel)]
        for key, fn in (jobs if i % 2 == 0 else jobs[::-1]):
            start = perf_counter_ns()
            fn()
            samples[key].append((perf_counter_ns() - start) / 1e6)
    return {key: {'median_ms': float(np.median(v)),
                  'min_ms': min(v), 'max_ms': max(v), 'samples_ms': v}
            for key, v in samples.items()}


def main():
    parser = argparse.ArgumentParser(description='Gri seviye görüntü işleme ve thread süre karşılaştırması')
    parser.add_argument('--image', type=Path)
    parser.add_argument('--out', type=Path, default=Path('sonuclar'))
    parser.add_argument('--size', type=int, default=2048)
    parser.add_argument('--repeats', type=int, default=31)
    args = parser.parse_args()
    if args.size < 2 or args.repeats < 3:
        parser.error('--size en az 2, --repeats en az 3 olmalı.')
    if args.image:
        with Image.open(args.image) as im:
            original = np.asarray(im.convert('L')).copy()
    else:
        original = test_image(args.size)
    if min(original.shape) < 2:
        parser.error('Görüntünün her boyutu en az 2 piksel olmalı.')
    out = args.out
    out.mkdir(parents=True, exist_ok=True)


    q6 = original >> 2
    q6_view = np.rint(q6.astype(np.float32) * 255 / 63).astype(np.uint8)
    offsets = [-60, -20, 20, 60]
    parts = quadrants(original)
    serial_dst, parallel_dst = np.empty_like(original), np.empty_like(original)
    serial_parts, parallel_parts = quadrants(serial_dst), quadrants(parallel_dst)

    def bright_serial():
        for src, dst, value in zip(parts, serial_parts, offsets):
            brightness(src, dst, value)

    def hist_serial():
        return np.sum([histogram(part) for part in parts], axis=0)

    with ThreadPoolExecutor(max_workers=4) as pool:

        barrier = Barrier(4)
        futures = [pool.submit(barrier.wait) for _ in range(4)]
        for future in futures:
            future.result()

        def bright_parallel():
            futures = [pool.submit(brightness, src, dst, value)
                       for src, dst, value in zip(parts, parallel_parts, offsets)]
            for future in futures:
                future.result()

        def hist_parallel():
            return np.sum(list(pool.map(histogram, parts)), axis=0)

        times = {'parlaklik': benchmark(bright_serial, bright_parallel, args.repeats),
                 'histogram': benchmark(hist_serial, hist_parallel, args.repeats)}
        h1, h4 = hist_serial(), hist_parallel()
        local_histograms = list(pool.map(histogram, parts))

    np.testing.assert_array_equal(serial_dst, parallel_dst)
    np.testing.assert_array_equal(h1, h4)
    np.testing.assert_array_equal(h4, histogram(original))
    assert int(h4.sum()) == original.size
    np.testing.assert_array_equal(q6, original // 4)
    assert int(q6.max()) <= 63


    scaled = np.floor(original.astype(np.float32) * .75).astype(np.uint8)
    shifted = np.floor(original.astype(np.float32) * .75 + 20).astype(np.uint8)
    difference = shifted.astype(np.int16) - scaled.astype(np.int16)
    assert np.all(difference == 20)

    edge = np.array([[0, 1, 254, 255]], dtype=np.uint8)
    edge_out = np.empty_like(edge)
    brightness(edge, edge_out, 60)
    np.testing.assert_array_equal(edge_out, [[60, 61, 255, 255]])
    brightness(edge, edge_out, -60)
    np.testing.assert_array_equal(edge_out, [[0, 0, 194, 195]])

    arrays = {'orijinal': original, '6bit_kodlar': q6, '6bit_gosterim': q6_view,
              'parlaklik_4_parca': parallel_dst, '075_carpim': scaled,
              '075_carpim_20_ekleme': shifted}
    for name, a in arrays.items():
        Image.fromarray(a).save(out / f'{name}.png')
    fig, axes = plt.subplots(2, 3, figsize=(12, 8))
    panels = [(original, 'Orijinal: 8-bit'), (q6_view, '6-bit: 64 seviye (0–255 gösterim)'),
              (parallel_dst, 'Parçalar: −60 / −20 / +20 / +60'),
              (scaled, 'floor(0.75 × I)'), (shifted, 'floor(0.75 × I + 20)'),
              (difference, 'Fark: her pikselde +20')]
    for ax, (a, title) in zip(axes.flat, panels):
        ax.imshow(a, cmap='gray', vmin=0, vmax=255)
        ax.set_title(title)
        ax.axis('off')
    fig.suptitle('Tüm paneller aynı parlaklık ölçeğini kullanır: 0–255')
    fig.tight_layout()
    fig.savefig(out / 'gorsel_karsilastirma.png', dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(2, 3, figsize=(12, 6))
    for ax, hist, title in zip(axes.flat, local_histograms + [h4, h4-h1],
                              ['Sol üst', 'Sağ üst', 'Sol alt', 'Sağ alt',
                               'Birleştirilmiş ana histogram', '4 thread − 1 thread farkı']):
        ax.plot(np.arange(256), hist, linewidth=1)
        ax.set(xlim=(0, 255), title=title, xlabel='Piksel değeri', ylabel='Piksel sayısı')
    fig.tight_layout()
    fig.savefig(out / 'histogramlar.png', dpi=150)
    plt.close(fig)

    metrics = {name: {'min': int(a.min()), 'max': int(a.max()),
                      'mean': float(a.mean()), 'std': float(a.std())}
               for name, a in arrays.items()}
    result = {'source': str(args.image) if args.image else 'Sentetik test görüntüsü; seed=42',
              'shape': list(original.shape), 'repeats': args.repeats,
              'system': platform.platform(), 'python': platform.python_version(),
              'numpy': np.__version__, 'logical_cpu_count': os.cpu_count(),
              'timings': times, 'metrics': metrics,
              'difference_min': int(difference.min()), 'difference_max': int(difference.max()),
              'checks': 'Parlaklık, histogram, piksel toplamı, nicemleme ve sınır kontrolleri geçti.'}
    (out / 'olcumler.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    np.savetxt(out / 'histogramlar.csv', np.column_stack([np.arange(256), *local_histograms, h4]),
               delimiter=',', fmt='%d', header='deger,sol_ust,sag_ust,sol_alt,sag_alt,ana', comments='')
    rows = []
    for label, item in times.items():
        one, four = item['1_thread']['median_ms'], item['4_thread']['median_ms']
        rows.append(f'| {label} | {one:.3f} | {four:.3f} | {one-four:.3f} | {one/four:.2f}× |')
    report = f'''# Gri seviye görüntü işleme sonuçları

Kaynak: {result['source']}. Boyut: {original.shape[1]} × {original.shape[0]} piksel.

## 1. 8-bit → 6-bit nicemleme

`Q = I // 4` dönüşümü 0–255 değerlerini 0–63 kodlarına indirger. Her dört ardışık giriş değeri aynı koda dönüşür. `6bit_kodlar.png` bu kodları 8-bit PNG içinde saklar; fiziksel olarak 6-bit paketlenmiş bir dosya değildir. Görsel karşılaştırma için `round(Q × 255 / 63)` kullanılır. Bu işlem 64 seviyeyi 0–255 aralığına yayar; kaybolan ayrıntıyı geri getirmez.

## 2. Dört parçada parlaklık

Orijinal görüntü sol üst, sağ üst, sol alt ve sağ alt olarak bölünür. Sırasıyla −60, −20, +20 ve +60 eklenir: `J = clip(I + b, 0, 255)`. İşlem öncesinde int16 dönüşümü yapılarak uint8 taşması engellenir. Tek thread aynı dört parçayı sırayla, dört thread eşzamanlı görevler olarak işler. Ayrı çıktı bölgelerine yazıldığından yazma çakışması yoktur. Tek boyutların artan satır/sütunları alt/sağ parçada kalır.

## 3. Süre karşılaştırması

| İşlem | 1 thread (ms) | 4 thread (ms) | Kazanım: T1 − T4 (ms) | Hızlanma: T1 / T4 |
|---|---:|---:|---:|---:|
{chr(10).join(rows)}

Her değer 3 ısınma turundan sonra {args.repeats} ölçümün medyanıdır. Koşum sırası dönüşümlüdür. Disk okuma/yazma, grafik üretimi, havuzun ilk kuruluşu ve çıktı tamponlarının ayrılması süreye dahil değildir. Görev gönderme, bekleme, hesap içi geçici diziler ve histogramların birleştirilmesi dahildir. Bu, kurulmuş bir thread havuzunda işlem süresini ölçer; programın toplam açılış süresi değildir. Her iki sürüm de aynı dört parça üzerinde aynı işi yapar.

Python `ThreadPoolExecutor` gerçek işletim sistemi thread'leri kullanır. Yoğun hesaplar NumPy'nin yerel kodunda çalışır; saf Python piksel döngüsü kullanılmaz. Dört thread'in dört kat hızlanması beklenmemelidir: görev maliyeti, bellek bant genişliği, görüntü boyutu ve sistem yükü sonucu etkiler. 1'in altındaki hızlanma oranı dört thread'in daha yavaş olduğunu gösterir. Sonuçlar bu çalıştırmaya aittir.

## 4. Paralel histogram

Her parça için 256 kutulu bir yerel histogram `bincount` ile hesaplanır. Ana histogram `H[k] = H₀[k] + H₁[k] + H₂[k] + H₃[k]` ile oluşturulur. Ortak bir sayacı değiştirmek yerine yerel diziler toplanır. Histogramlar orijinal 8-bit görüntü üzerinde hesaplanır. Tek thread de aynı yerel histogramları sırayla üretip toplar.

Doğrulama: tek/dört thread histogramları ve doğrudan tüm görüntü histogramı birebir eşittir. Histogram toplamı {original.size} pikseldir. Parlaklık çıktıları da birebir eşittir.

## 5. 0.75 ile çarpma ve 20 ekleme

`A = floor(0.75 × I)` ve `B = floor(0.75 × I + 20)` uygulanır. Giriş 0–255 olduğundan sonuçlar sırasıyla 0–191 ve 20–211 sınırları içindedir; kırpma gerekmez. Her piksel için `B − A = 20` olur. +20 eklenmesi ortalamayı 20 artırır; standart sapmayı ve maksimum-minimum farkını değiştirmez. 0.75 çarpanı ise girişin parlaklık aralığını daraltır. Görseller aynı 0–255 ölçeğinde gösterildiğinden otomatik kontrast yanıltması yoktur.

| Görüntü | Minimum | Maksimum | Ortalama | Standart sapma |
|---|---:|---:|---:|---:|
'''
    for name in ['orijinal', '075_carpim', '075_carpim_20_ekleme']:
        m = metrics[name]
        report += f"| {name} | {m['min']} | {m['max']} | {m['mean']:.3f} | {m['std']:.3f} |\n"
    report += '\n![Görsel karşılaştırma](gorsel_karsilastirma.png)\n\n![Histogramlar](histogramlar.png)\n'
    (out / 'rapor.md').write_text(report, encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
