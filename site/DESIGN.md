# linelore visual design: Swiss poster, kinetic type

Replaces the earlier card-catalog direction (index cards, oak drawer, manila paper, typewriter, red stamp). None of that is used any more.

## Reference
A Swiss International Typographic Style poster (Müller-Brockmann concert posters, Ruder's typographic exercises): a white sheet, one grotesk family, a strict column grid, ragged-right text, enormous type set against small type, and one signal colour.
Metaphor: **one line of code is the subject of the poster.** linelore takes that line apart and runs leader lines from the part you picked to four numbered answers: 01 commit, 02 pull request, 03 issue, 04 review comment. Together they answer "why".

## Colour (only these)
| role | hex |
|---|---|
| ground | `#ffffff` |
| type, rules | `#0a0a0a` |
| the one accent: leader lines, numbers, current highlight | `#ff5b00` (international orange) |
| hairlines, column guides | `#e4e4e4` |

No red, no beige or cream, no gradients, no shadows, no tints. Orange is never used for body text (contrast). It appears only on large numbers, on lines and blocks, and on black-on-orange highlights.

## Type
- **Schibsted Grotesk**, variable 400–900, self-hosted woff2 (OFL, `site/fonts/`). It's the only family. Display: 900, tight leading (0.86), negative tracking. Body: 400, 18–20px. Labels: 700, uppercase, +0.04em tracking.
- **Fragment Mono** 400 (OFL) only for the line of code and the shell commands.
- No serif, no typewriter face, no Inter, no system UI stack beyond fallbacks.

## Texture and rendering
Flat. No texture, shadow, border radius, skeuomorphic objects or illustration. Everything is type, 1–2px rules, solid orange squares and white space. The rendering technique is **kinetic typography**: CSS transforms and SVG strokes driven by a small vanilla JS file (no framework).

## Layout
- A strict 12-column grid (max 1440px, 24px gutters, 4 columns on mobile). Column guides show as faint `#e4e4e4` hairlines in the hero.
- Flush-left, ragged-right. Nothing is centred.
- Hero: the headline "Why is this line like this?" is set huge enough to fill the measure. The code line sits on columns 1–12 in Fragment Mono. Numbered answers 01–04 sit asymmetrically on columns 5–12, with oversized orange numerals at the left of each.
- The sections below are numbered (A, B, C) with a thick black top rule, a label on columns 1–3 and content on columns 4–12. No cards, panels or centred objects.
- Hop 02 carries a small label/value list of the per-forge API calls (GitHub, GitLab, Gitea/Forgejo): 700 uppercase labels, Fragment Mono values that break only after `/`, one `#e4e4e4` hairline above. Added in v0.3 as a content update; no new colour, type or texture.
- Section C, "In your editor" (v0.4), is a content addition: no new colour, type or texture. The four editor names are a tab row set in Schibsted Grotesk at display size, weight 400, and the chosen one goes to 900 with the orange bar under it. Below: the keystroke in Fragment Mono at poster size, then four real source lines with line 795 on an orange block and the plugin's real output in a 2px black frame with a black title bar. Labels get a 3px orange underline; nothing has a radius or a shadow. On phones the output's mono size is fitted to the frame so each real line stays one line.
- Footer is one black rule plus small type.

## Animation
1. On load (the hero): the code line appears very large, letter-spaced to fill the width. It then breaks apart: characters spread on a stagger and the line re-sets to reading size. The selected segment (`verify`) is boxed in orange, and four orange leader lines draw out (SVG `stroke-dashoffset`) to 01, 02, 03 and 04, which slide in from the right one at a time. Easing is crisp, `cubic-bezier(.2,.9,.1,1)`, 380–600 ms, like a layout snapping into place, never bouncy.
2. On scroll: each numbered step's big heading scales from 0.9 and slides in on the grid as it enters (IntersectionObserver plus CSS transitions).
3. Micro: the install command copies on click and the button flips to an orange block ("Copied"). Nav links get an orange underline bar.
4. Section C: the active tab's weight goes 400 → 900 as the orange bar slides under it; the keystroke types in a character at a time; the orange line block wipes in from the left; the output frame opens top-down (`clip-path`) and its lines slide in on a 22 ms stagger. The first time the tabs come into view the section goes through all four editors once (3.6 s each, a 2px black rule fills to show the time left) and stops for good at the first pointer, wheel, touch or focus. Arrow keys, Home and End move between tabs. Without JavaScript all four panels are shown, one after another.
5. `prefers-reduced-motion: reduce`: no transforms or stroke drawing, no tour; the final layout is shown at once.

## Logo
A pure wordmark: **`l:42`** in Schibsted Grotesk 900, black, with a solid international-orange square at the baseline after it (the "line" you point at). No app-icon tile, no rounded square, no illustration. Files: `site/favicon.svg` (the favicon is "l:" plus the square, so it stays legible at 16px), `docs/assets/logo.svg`, `assets/logo-512.png` and `site/logo-512.png` (white square canvas, wordmark set flush-left on the grid).

## OG image and social preview
White ground with "Why is this line like this?" in black 900, set on a 12-column grid, flush left. One orange leader line runs from a mono code fragment to small numbered labels 01–04, plus the wordmark. `site/og-image.png` (1200×630), `docs/assets/og-docs.png` (1200×630) and `site/social-preview.png`, also copied to the repo-root `og-social-preview.png` (1280×640).

## Docs site
MkDocs Material keeps its structure, with colours and fonts switched to the above: white, black, orange accents, Schibsted Grotesk text and Fragment Mono code. Content is unchanged.

## Difference self-check against design/registry.md
| axis | linelore | closest other | different? |
|---|---|---|---|
| base tone | pure white, neutral | toolsmoke warm paper #f2eee3; runbill cool concrete #c9ccd1; certfan near-black; agentckpt LCD green | yes: the only pure-white neutral ground |
| palette | #ffffff / #0a0a0a / #ff5b00 / #e4e4e4 | certfan acid lime and hot pink; runbill cobalt; toolsmoke vermilion | yes: orange is used nowhere else, and there's no red or beige |
| type | Schibsted Grotesk + Fragment Mono | Fraunces/Courier Prime, Silkscreen/Pixelify, Anybody/Atkinson, Unbounded/Red Hat | yes: no family shared |
| texture | flat, no texture or shadow | certfan is also flat but dark, generative line art | yes: different tone and technique |
| rendering | kinetic typography | print document, pixel art, generative dataviz, isometric 3D | yes |
| layout | strict 12-column Swiss grid, flush-left, giant type, numbered 01–04 | certfan asymmetric 12-column dataviz plate (dark, chart-led) | yes: type-led on white, no chart |
| animation | letters split, scale and slide; leader lines draw | typing and stamping, steps() sprites, fan strokes, falling blocks | yes |
| logo | type-only wordmark "l:42" + orange square | stamp wordmark, pixel flag, fan of lines, isometric cubes | yes |
Also checked against the cross-project bans: no warm paper, no red ink or stamps, no typewriter face, no line-by-line receipt printing, no stacked paper with hard shadows, no rounded app-icon logo. Against the playbook bans: no dark background with cyan/purple, no gradient text, no glow, no glass, no left-copy/right-card hero, no three feature cards, no Inter + mono default.
