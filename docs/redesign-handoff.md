# Redesign handoff — Wave 1

Visual assets for the approved automotive-service chat. This wave does not change the interface. Text, controls, and replies stay real UI in Wave 2. Do not use the approved mockup, or any screenshot of it, as the page background.

## Asset inventory

All paths are relative to the repository root. Canvas sizes below are the files on disk.

| File | Role | Actual size | Format | Alpha |
| --- | --- | --- | --- | --- |
| `web/assets/redesign/masters/architectural-light.jpg` | Native background master | 1280×720, 119 KB | JPEG, opaque | none |
| `web/assets/redesign/architectural-light.jpg` | Web background | 2560×1440, 200 KB | JPEG, opaque | none |
| `web/assets/redesign/masters/glass-metal-ornament.jpg` | Native ornament master, white field | 864×1152, 114 KB | JPEG, opaque | none |
| `web/assets/redesign/glass-metal-ornament.png` | Web ornament, lossless | 864×1152, 554 KB | PNG, sRGBA | binary |
| `web/assets/redesign/glass-metal-ornament.webp` | Smaller ornament | 864×1152, 57 KB | WebP, quality 92, lossless alpha | binary |
| `web/assets/redesign/glass-metal-shadow.png` | Synthetic contact shadow | 864×1152, 13 KB | PNG, sRGBA | soft |

The generator’s supported frames were 16:9 and 3:4. It returned 1280×720 and 864×1152. The 2560×1440 JPEG is a Lanczos resample of the 1280×720 master, not a higher-resolution render. The ornament was not resampled to 1200×1600; scaling belongs in CSS so the hard silhouette stays sharp.

### Placement

- `architectural-light.jpg` is the only page background. Cover the viewport. Keep the application window on the quiet center and right. The light bands belong to the left margin.
- The ornament and shadow sit inside the left column of that window, above the left-column headline. They are not the page background.
- Prefer the PNG ornament. Use the WebP only if the PNG weight is a problem; its alpha matches the PNG, and the color is lossy.
- The shadow PNG uses the same canvas as the ornament. Stack it directly behind the ornament, same origin and same displayed size. It is a drawn ellipse, not a piece extracted from the render.

## Color, layout, type, shadow

Samples are from the 1024×640 approved reference.

| Token | Hex | Where it was sampled |
| --- | --- | --- |
| Page light | `#FBF7EE` | Outer top-left |
| Warm shade | `#EBE4DA` | Left outer wall |
| Left panel | `#EFE7DA` | Left column field |
| Workspace | `#FAF6F3` | Right panel |
| Composer well | `#F9F5F2` | Input trough |
| Hairline | `#E5E2DD` | Panel edge |
| Ink | `#2B2C30` | Main headline |
| Petrol | `#032A32` | RU pill and send control, clustered around `#002930`–`#0B212E` |
| Mark | `#012E3A` | Small brand mark, slightly bluer than the buttons |

Secondary copy is a warm gray, lighter than the ink. Do not invent a precise gray; sample a glyph when the type is set. Borders stay 1px and warm, not cool blue.

The reference frame is 1024×640. The floating window runs about x=42 to x=979. The left column ends near x=353, so the split is about 33% / 67%. Keep that ratio on desktop: a centered window, not a full-bleed app. Outer scene remains visible around the window. Window radius is large (on the order of 28px at that frame). Prompt chips are softly rounded. The composer is a pill. The send control is a petrol circle.

Headlines are large, dark, and medium weight, with open line height. UI labels stay small. The page already uses the browser sans for interface text and a monospace stack only for developer code. Stay on a neutral system sans. Size and weight carry the reference; do not add a webfont in this pass.

Window shadow is wide, soft, and warm, offset downward. Chips use the hairline plus a very small lift. The ornament’s contact shadow is the separate PNG, not a heavy black drop under the whole window.

## Cropping

Desktop: `background-size: cover`, position around `center 42%`, so the floor stays low and the quiet wall sits behind the window. The left light may show in the margin.

Narrow screens: stack the chat under a short left band, or drop the ornament if the column gets too thin. Position the background `left center` so the stripes stay at the edge and the text sits on the quiet wall. Do not crop through the composer. The ornament, when shown, is static. The message list and composer keep their current behavior and fill the width.

Ultrawide: keep the window centered at a readable max width. Let the quiet right side of the photograph fill the extra space.

## Motion

The current tilt is hard to see for two local reasons. It is bound to the small brand mark (`data-tilt-max="3"` on a roughly 46×40 target), and the glare pseudo-element is `z-index: -1`, so it paints behind that opaque mark. Large rectangles are also clamped to 1.8°, and every target is clamped to 5°.

Wave 2 should tilt only the ornament bitmap:

1. Left-panel surface, stationary.
2. `glass-metal-shadow.png`, stationary, or shifted a few pixels at most. It does not rotate as its own object.
3. `glass-metal-ornament.png` on one tilt plane. Perspective about 1000px. A peak near 6° is enough to read on this artwork. The existing 1.8° large-rect clamp and 5° hard cap will hide that unless this target is exempted. Ease back to 0° on pointer leave; the current 0.17 ease is a good return.
4. A CSS glare disc drawn after the image, in front of it, following the pointer. Do not reuse the behind-the-element `::after` for this bitmap.
5. Left-column headline, chat transcript, and composer stay outside the tilting node.

This is one flat picture rotating in perspective. The glass panes and the ring cannot move separately. Partial alpha was not produced: the silhouette and the ring opening are fully transparent, and the panes themselves are opaque pixels. A page color will show through the ring hole and around the group. It will not show through the glass.

Disable the tilt, the glare, and any shadow shift for `prefers-reduced-motion: reduce`, `(pointer: coarse)`, and `(hover: none)`. The current motion script already ignores non-mouse pointers and turns the effect off for those queries. Keep that. The ornament and shadow still render, flat.

## Product constraints to preserve

- Interface copy stays bilingual. Russian and Turkish already live in `web/locales/ru.json` and `web/locales/tr.json`.
- Assistant replies stay Russian only. `webapp/chat_service.py` appends that instruction on every chat request. The locale switch does not change it.
- Do not invent prices, opening hours, availability, policies, or completed bookings.
- The approved chips are conversation prompts. The shipped starters are already questions in both locale files. Restyle them; do not turn them into a booking flow.
- The developer panel stays a configuration display. The gear in the mockup is not a new product feature.

## Limitations

- No separate glass-plane or metal-ring renders were made. A second generation would not share pixels with the first, so those layers would not align.
- Alpha is binary. Edges can stair-step when scaled up. A thin light fringe remains on the lower-right of the front pane and shows most on a dark field. On `#EFE7DA` it is slight.
- The front pane is milkier than the reference, and the group is a little looser. Materials and palette match; it is not a pixel recreation.
- The background is an empty ivory room. It has no interface, type, cars, or people. Detail is that of the 1280×720 master.
- Application HTML, CSS, JavaScript, and Python were not changed.
