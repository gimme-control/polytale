# Night Market — art

All art is generated offline by `scripts/generate_art.py` with `gemini-3-pro-image` and is never
drawn at runtime. The script skips files that exist; `--force market/<name>` regenerates one,
`--rederive market/<name>` rebuilds it from the cached raw output with no model call, `--only market`
limits a run to this scene, `--list` shows status. Full prompt text is in the script (`STYLE`,
`NO_TEXT`, `MARKET_BG`, `MOODS`, `COVERS`, `OBJECTS`, `ILLUSTRATIONS`). PNG masters (raw 2752x1536 backgrounds, raw
green/blue-screen props) live in `cache/art_raw/market/`, which is gitignored and not served.

Style brief: mature, cinematic stylized-realism painting for adults; first-person POV; no text,
characters, digits, logos or labels anywhere.

- **Moods** are the neutral frame with only a feathered box around the character (`npc_region`
  in `LAYOUT.json`) taken from a model edit, colour-matched to the neutral frame first. Outside
  that box the three frames share the same source pixels; the only difference left is lossy
  WebP noise (mean under 1 level per channel), so a crossfade does not flicker.
- **Props** are painted on a saturated green screen (blue for food with green garnish) and cut
  with the difference keyer in `tools/matte.py` (`soft_key_cutout`), which keeps glass and steam
  translucent and turns the painted contact shadow into translucent black. Tests:
  `scripts/test_matte.py`.
- **Layout**: `LAYOUT.json` uses background fractions, origin top-left; `x,y` = object
  centre-bottom, `h` = object height / background height. `scripts/render_layout_debug.py`
  redraws `debug_layout.png` (review only, not for players) and fails on overlapping boxes.

| File | Size | What it shows |
| --- | --- | --- |
| `bg.webp` | 2400x1350 | First-person view standing at a night-market stall: vendor (woman, 50s, indigo apron) right of centre, waist-up, neutral, hands on the steel counter. Lit steel back counter with clear stretches either side, steaming stock pot at the far left, bamboo steamers at the far right, string bulbs, bokeh only in the background (no signs). |
| `bg_pleased.webp` | 2400x1350 | Same frame; amused closed-mouth smile. |
| `bg_puzzled.webp` | 2400x1350 | Same frame; sceptical frown, head tilted, one hand raised palm-up at shoulder height. |
| `cover.webp` | 1920x1080 | Misty night-market lane after rain, string bulbs, hero stall with steaming pot, steamers and bowls on the right, distant silhouettes only. No signs. |
| `obj_noodles.png` | 768x731 RGBA | Bowl of beef noodles with egg and scallions, chopsticks across the rim, steam (blue screen). |
| `obj_dumplings.png` | 768x531 RGBA | Plate of eight pan-fried dumplings (blue screen). |
| `obj_chili.png` | 395x768 RGBA | Unlabeled glass jar of red chili oil with a spoon. |
| `obj_scarf.png` | 284x768 RGBA | v3. Mei's burgundy knitted scarf, knotted once, hanging from a small iron hook. Generated with the photo as a second reference; `hanging` props get no floor shadow. |
| `obj_photo.png` | as bar | v3. Byte-identical copy of the bar's photo. |
| `ending_reunited.webp` | 1920x1080 | v3 ending. First-person on a metro platform: the last train with its doors open and warm light spilling out, Mei mid-turn with a huge grin and one arm raised. Empty carriage, blank panels. Photo used as the identity reference. |
| `ending_late.webp` | 1920x1080 | v3 ending. The same kind of platform, empty, two red tail lights receding in the tunnel; Mei on a bench shrugging with a wry smile beside two steaming takeaway bowls. |
| `obj_beer.png / obj_water.png / obj_money.png` | as bar | Byte-identical copies of the bar's files, so recall is visually identical. |
| `LAYOUT.json` | | `aspect`, `npc_anchor` (mouth), `npc_region` (mood blend box), per-object `display` / `counter` / `npc` spots. |
| `debug_layout.png` | 1200x2025 | Review sheet: display spots, counter spots (on the puzzled frame), outlined boxes. |
