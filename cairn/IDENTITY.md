# IDENTITY.md

## Name

Cairn. Placeholder, but a decent one. A cairn is a stack of rocks that says someone was here and the way is this direction. Unbranded, functional, built by whoever came before. That is the product.

## Positioning

A field instrument, not a lifestyle app. Cairn is closer to a compass than to Instagram.

## Voice

Plain and terse. Numbers over adjectives. The app says "1,240 ft gain, 4.2 mi" and never says "Moderate difficulty, great for families!" Difficulty ratings are subjective and get skipped in v1.

No exclamation points. No encouragement. No streaks, badges, or celebration animations. The user is an adult going for a walk.

Error states are honest: "No downloaded map for this area" beats "Oops! Something went wrong."

## Visual direction

Topographic and utilitarian. Reference points are USGS quad sheets, Suunto instrument faces, and old trail signage.

- **Palette**: warm off-white paper base (`#F5F2EC`), deep ink for text (`#1A1A17`), a single burnt orange accent for the user's position and active states (`#C4562B`), contour brown for elevation (`#8A7A63`). Trails render as a dark ink line. No gradients on UI chrome.
- **Dark mode is required**, not optional. It is used at dawn and dusk in the field. Dark mode is a near-black (`#12120F`) with the same orange accent, which stays legible in low light and does not destroy night vision as badly as blue.
- **Type**: one grotesque for UI, one mono for numbers. Numbers (distance, elevation, coordinates, time) always render in mono and always tabular-figure aligned. This is the strongest single visual signature of the app.
- **Density**: information-dense on trail detail, extremely sparse in recording mode. While recording, the screen shows four numbers and a map. Nothing else.
- **Touch targets are large.** This is used with cold hands, gloves, and sweat. Minimum 48px, prefer 56px for anything used while moving.
- **No hamburger menus.** Bottom tab bar, three tabs maximum: Map, Tracks, Downloads.

## What it must never look like

Rounded pastel cards with stock photography of smiling people on mountains. No hero images. No photography in the UI at all in v1, which is convenient since there is no photo data.

## Attribution

OSM attribution is permanent and visible on the map, not buried in a settings page. This is both a license requirement and a statement about where the data comes from.
