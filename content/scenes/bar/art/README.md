# The Corner Bar — art

All art is generated offline by `scripts/generate_art.py` with `gemini-3-pro-image` and is never
drawn at runtime. The script skips files that exist; `--force bar/<name>` regenerates one,
`--rederive bar/<name>` rebuilds it from the cached raw output with no model call, `--only bar`
limits a run to this scene, `--list` shows status. Full prompt text is in the script (`STYLE`,
`NO_TEXT`, `BAR_BG`, `COVERS`, `ILLUSTRATIONS`). PNG masters (raw 2752x1536 backgrounds) live in
`cache/art_raw/bar/`, which is gitignored and not served.

Style brief: mature, cinematic stylized-realism painting for adults; first-person POV; no text,
characters, digits, logos or labels anywhere.

**Layout**: `LAYOUT.json` carries `aspect` and `npc_anchor` (the character's mouth, in background
fractions, origin top-left). It is what the client uses to frame the speaker.

| File | Size | What it shows |
| --- | --- | --- |
| `bg.webp` | 2400x1350 | First-person view from a bar stool, the character centred and waist-up behind the counter, lit back counter behind him, empty near counter across the bottom ~27%. |
| `cover.webp` | 1920x1080 | Rain-wet corner street at night, glowing fogged door and window, abstract neon ring, parked bicycle. Nobody in the street. |
| `ending_kickoff.webp` | 1920x1080 | The fan zone under the big screen at kickoff: a sea of scarves, the match about to start. Used by the `found` ending. |
| `ending_late.webp` | 1920x1080 | Outside the fence, watching through a gap with the unlucky. Used by the `outside` ending. |
| `LAYOUT.json` | | `aspect`, `npc_anchor` (mouth). |

Story key art lives one level up: `content/title.webp` (1920x1080, asset name `story/title`).

## Known gap

`bg.webp` still shows the original **bartender in an apron**. The scene's character is now a
football fan in a team shirt and scarf on final night. Regenerating it means an image-model call
(`scripts/generate_art.py --force bar/bg`), which costs credits, so it has been left alone. Mood
frames (`bg_pleased` / `bg_puzzled`) and the object cutouts (`obj_*.png`) were deleted with the
mood and item systems.
