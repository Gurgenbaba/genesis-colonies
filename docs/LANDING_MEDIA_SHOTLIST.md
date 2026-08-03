# Landing Media Shotlist

Marketing assets for `/` live under `static/img/landing/`.

## Generate (canonical)

```bash
pip install playwright imageio-ffmpeg Pillow
playwright install chromium
python tools/capture_landing_media.py
```

The script:

1. Creates a temp DB + showcase colony (buildings, resources, ships)
2. Starts Flask on a free port
3. Captures 1920×1080 WebP screenshots of Overview, Galaxy, World Boss, Fleet, Inventory, Empire, Story, Politics
4. Builds short Ken-Burns moment loops
5. Assembles `hero.mp4` / `hero.webm` (~28s) + `hero-poster.webp`

## File map

| Path | Role |
|------|------|
| `hero.mp4` / `hero.webm` | Hero loop |
| `hero-poster.webp` | Poster / reduced-motion fallback |
| `trailer.mp4` / `trailer.webm` | Optional 1-min trailer (manual later) |
| `shots/shot-01-overview.webp` … `shot-08-politics.webp` | Gallery |
| `moments/moment-0N-*.webm` (+ `.webp` still) | Live Moments strip |

## Hero cut order (capture order)

1. Overview  
2. Galaxy  
3. World Boss  
4. Fleet  
5. Inventory  
6. Empire  
7. Story Ops  
8. Galactic Politics  
9. Endcard: *Build your Empire. Conquer the Galaxy. / PLAY NOW*

## Manual upgrades (optional)

Replace individual moment WebMs with OBS clips (same filenames) for:

- Resources ticking up
- Building queue completing
- Fleet launch animation
- Boss combat VFX
- Lootbox / case opening

Budgets (soft): hero ≤ ~8–12 MB, shots ≤ ~200 KB each WebP, moments ≤ ~1–2 MB each.

## Runtime

`game/landing_media.py` → `resolve_landing_media()` scans the folder. Missing files → CSS atmosphere only; gallery/moments sections omit themselves.
