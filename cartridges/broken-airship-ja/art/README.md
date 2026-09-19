# Broken Airship — art

All art is generated offline by `scripts/generate_art.py` (idempotent: it skips any file that
exists; `--force <name>` regenerates, `--rederive <name>` rebuilds from the cached raw model
output in `cache/art_raw/` with no model call). Full prompt text lives in the `*_PROMPT`
constants in that script; summaries are below. Every model call is logged to
`cache/art_raw/calls.jsonl`.

Cutouts are matted by `tools/matte.py` (edge-flood chroma matte adapted from Arbitale, plus
`purge_key` / `remove_hairlines` / `drop_small_islands` / `trim_to_subject`), tested offline by
`scripts/test_matte.py`. Stage placement is in `LAYOUT.json`; `scripts/render_layout_debug.py`
redraws `debug_layout.png` from it.

| File | Size | Model | Prompt (summary) / derivation |
| --- | --- | --- | --- |
| `plate_base.png` (+ `.webp`) | 2229x1244 RGB | gemini-3-pro-image, 16:9 2K | Ghibli-adjacent gouache storybook painting at dusk: grassy cliff-top airfield, grounded patched-canvas airship with a wooden, brass-trimmed hull, a closed and locked brass engine hatch visible mid-frame, a lantern-lit workshop shed on the left, open continuous meadow on the right third, and a storm with lightning over the sea. No people and no text. Native 2752x1536, downscaled so the PNG stays at or under 4 MB. |
| `plate_panel_open.png` (+ `.webp`) | 2229x1244 RGB | gemini-3-pro-image, base as reference | "Keep IDENTICAL, change ONLY: the engine hatch swung open showing glowing brass machinery." The result is masked-merged back into the base through a feathered circle at `fx.engine_panel` (r × 2.4), so every pixel outside the hatch matches the base exactly. |
| `plate_launched.png` (+ `.webp`) | 2229x1244 RGB | gemini-3-pro-image, base as reference | Same place and camera. The airship is airborne upper-right with its propellers blurred; the meadow where it sat is empty with dropped ropes at the stakes; the storm parts with a shaft of gold light. Shed, lanterns, crates and fence stay consistent. |
| `engineer.png` | 1064x2502 RGBA | gemini-3-pro-image, 9:16 2K, base as style reference | Full-body young Japanese woman airship engineer: dark bob, brass goggles on her head, oil-stained rust-orange jumpsuit with rolled sleeves, tool belt, boots, three-quarter pose with one hand raised palm-up. Painted on flat mint `#2ad4a0`, then matted, purged of key, trimmed (12px pad, feet on the bottom edge) and **mirrored** so she faces left toward the airship. |
| `engineer_portrait.png` | 768x768 RGB | gemini-3.1-flash-image, 1:1 1K, sprite as identity reference | Same character, head and shoulders, with a soft painted bokeh of lanterns and dusk sky behind. |
| `icon_key.png` | 512x512 RGBA | gemini-3.1-flash-image, 1:1 1K, base as style reference | Ornate antique brass engine key with a gear cutout in the bow, on mint; matted and contain-fit with a 20px margin. |
| `icon_map.png` | 512x512 RGBA | gemini-3.1-flash-image, 1:1 1K, base as style reference | Rolled parchment route map tied with a red silk ribbon, with faint coastline lines and no writing, on mint; matted the same way. |
| `cover.png` (+ `.webp`) | 2229x1244 RGB | gemini-3-pro-image, base as world reference | New low-angle hero composition of the same airship on the cliff edge, leaves in the wind, storm and lightning at the right, calm sky upper-right for a title. |
| `debug_layout.png` | 1114x1866 | (none) | Review sheet made from LAYOUT.json. Not shipped to players. |
| `LAYOUT.json` | (none) | (none) | Stage coordinates in plate fractions (origin top-left). `r` is a fraction of plate height. `state_overrides.launched` moves the `fx.airship` hotspot for `plate_launched.png`. |
