# Agent Guide

## Communication and naming

- Kullanıcıyla varsayılan olarak Türkçe iletişim kur.
- Kod, dosya, sistem ve commit adlarında İngilizce kullan.
- Mevcut runtime kurulumlarını ve mise yapılandırmasını değiştirme.

## Running web dashboard

- Arka plandaki dashboard, kullanıcı systemd servisi `accx-web.service` ile çalışır.
- Servis tanımı: `/home/onur/.config/systemd/user/accx-web.service`.
- Başlatma komutu: `/home/onur/.local/bin/accx web --no-open`.
- `/home/onur/.local/bin/accx`, bu depodaki `/home/onur/Code/accx/accx` dosyasına bağlanır. Kod değişikliklerinin çalışan backend'e yansıması için servisi yeniden başlat.
- Adres: `http://127.0.0.1:8765/`.
- Ayrı bir `accx web` süreci başlatmak yerine mevcut servisi kullan.

Yeniden başlatma ve kontrol:

```sh
systemctl --user restart accx-web.service
systemctl --user status accx-web.service --no-pager
curl --fail --retry 5 --retry-connrefused --retry-delay 1 --silent --output /dev/null http://127.0.0.1:8765/
```

Loglar:

```sh
journalctl --user -u accx-web.service -n 50 --no-pager
```

Sandbox kullanıcı systemd bus erişimini engellerse, servis komutlarını gerekli sandbox dışı araç izniyle çalıştır. Servisi `sudo systemctl` ile sistem servisi olarak yönetme.

Arayüz doğrulamasında sadece servisin HTTP 200 dönmesini kontrol etmek yeterli değildir. HTML içindeki asset sürümünü ve sunulan JavaScript içeriğini de doğrula. HTML, JS/CSS içerik hashlerini URL’ye ekler; böylece normal sayfa yenilemesi güncel dosyaları yükler.
