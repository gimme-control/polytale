# The Corner Bar — art

All art is generated offline by `scripts/generate_art.py` with `gemini-3-pro-image` and is never
drawn at runtime. The script skips files that exist; `--force bar/<name>` regenerates one,
`--rederive bar/<name>` rebuilds it from the cached raw output with no model call, `--only bar`
limits a run to this scene, `--list` shows status. Full prompt text is in the script (`STYLE`,
`NO_TEXT`, `BAR_BG`, `MOODS`, `COVERS`, `OBJECTS`, `ILLUSTRATIONS`). PNG masters (raw 2752x1536 backgrounds, raw
green/blue-screen props) live in `cache/art_raw/bar/`, which is gitignored and not served.

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
| `bg.webp` | 2400x1350 | First-person view from a bar stool: bartender (man, 40s, charcoal shirt, rolled sleeves, apron) centred, waist-up, neutral, both hands on the counter. Lit back counter behind him with clear stretches either side, dark bottles only at the far ends, empty near counter across the bottom ~27%, abstract magenta/teal neon at the right edge. |
| `bg_pleased.webp` | 2400x1350 | Same frame; small genuine smile, slight nod. |
| `bg_puzzled.webp` | 2400x1350 | Same frame; head tilted, eyebrow raised, one hand raised palm-up in front of his chest (kept inside his torso outline so it never crosses a display spot). |
| `cover.webp` | 1920x1080 | Rain-wet corner street at night, glowing fogged door and window, abstract neon ring, parked bicycle. Nobody in the street. |
| `obj_beer.png` | 241x768 RGBA | Unlabeled amber-brown beer bottle with condensation. |
| `obj_water.png` | 386x768 RGBA | Tall straight glass of still water; genuinely semi-transparent. |
| `obj_tea.png` | 768x507 RGBA | Dark Yixing clay teapot with one cup of tea, wisp of steam. |
| `obj_menu.png` | 564x768 RGBA | Closed oxblood leather menu with brass corners, standing as a tent, blank cover. |
| `obj_money.png` | 768x424 RGBA | Small stack of red-pink notes; print is abstract swirls only, no digits or portrait. |
| `obj_photo.png` | 768x744 RGBA | v3. Worn instant photo of Mei (late 20s, dark bob, burgundy knitted scarf, laughing, warm city bokeh), blank white border, rotated a few degrees. Keyed as an opaque prop (`solidify`), so lights inside the print cannot punch holes. |
| `obj_tab.png` | 462x768 RGBA | v3. Unpaid tab: brass bill spike with paper slips carrying pencil squiggles only (no characters or digits). |
| `obj_baijiu.png` | 624x768 RGBA | v3. Brim-full shot glass beside a small unlabeled white ceramic liquor bottle with a red cloth stopper. |
| `LAYOUT.json` | | `aspect`, `npc_anchor` (mouth), `npc_region` (mood blend box), per-object `display` / `counter` / `npc` spots. |
| `debug_layout.png` | 1200x2025 | Review sheet: display spots, counter spots (on the puzzled frame), outlined boxes. |

Story key art lives one level up: `content/title.webp` (1920x1080, asset name `story/title`): rain-wet street,
a lit train crossing an elevated line, the bar's glow on the right, market bulbs far down the lane
on the left, dark empty sky top-left for the title. The bar and market covers are its references.
