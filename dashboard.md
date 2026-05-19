# Nulm Dashboard — UI Redesign Brief

## Proje Bağlamı
Nulm, yerel makinede çalışan bir Python MCP sunucusudur.
AI ajanlarının dosya sistemi ve shell komutlarına erişimini
approval-based bir yapıyla denetler. Hedef kullanıcı:
terminalde rahat, güvenlik konusunda tavizsiz kıdemli developer.

## Mevcut Sorun
Şu anki dashboard jenerik, karaktersiz ve AI-slop görünümlü.
Emoji yok. Gradient orb yok. Rounded consumer-SaaS yok.
Projeye özgü bir kimliği yok.

## Tasarım Yönü: "Terminal Evolved"
Monospace font ağırlıklı tipografi (JetBrains Mono veya
Berkeley Mono gibi bir şey — Inter veya system-ui kesinlikle değil).
Dark theme zorunlu, varsayılan.
Renk paleti: koyu antrasit zemin (#0d0f14 civarı), tek keskin
accent rengi (elektrik mavisi #2563eb veya neon yeşili #16a34a —
ikisinden birini seç ve orada kal). Status renkleri: sarı=pending,
kırmızı=blocked/danger, mavi=running, yeşil=success.
Referans estetik: Linear, Raycast, Warp — tüketici değil developer tool.
Hairline border'lar (1px, düşük opaklıkta). Geniş renk blokları yok.

## Teknik Kısıtlar
Vanilla JS + CSS değişkenleri — framework yok.
Mevcut API endpoint'leri: /api/status, /api/approvals/{id}/approve,
/api/approvals/{id}/reject, /api/messages (POST), /api/tasks.
Token query param ile auth: ?token=...
Polling tabanlı güncelleme (WebSocket yok şu an).

## Mevcut Yapı
4 tab: Overview, Activity, Approvals, Messages.
Overview: metric kartları (session count, task stats, pending approvals).
Approvals: inline approve/reject butonları olan liste.
Messages: text input + gönderilen mesaj listesi.

## Ne İsteniyor
Bu dosyaları tamamen yeniden yaz:
- web/src/styles.css
- web/src/app.js (sadece görsel/render kısımları — API logic'e dokunma)
- web/index.html (font import ekle)

Karakter isteği: Bir insan tasarımcının elinden çıkmış gibi görünsün.
Her tab'ın kendine özgü bir hissi olsun ama sistem tutarlı kalsın.
Information density yüksek, gereksiz whitespace yok.
Animasyon varsa sadece fonksiyonel geri bildirim için (spinner,
status pulse) — dekoratif animation yok. metnini içeren bir md yaz
