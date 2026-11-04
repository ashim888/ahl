---
name: Ajna Health Lens
description: Illuminating Health Research. A journal-backed health news site set like a broadsheet, plus the editorial team's workspace.
colors:
  ink: "#111110"
  paper: "#ffffff"
  newsprint: "#f5f4f1"
  card-white: "#ffffff"
  rule-grey: "#e6e3df"
  muted-stone: "#e8e5e0"
  graphite: "#6b6860"
  press-red: "#c0392b"
  press-red-deep: "#a93226"
  press-red-on-ink: "#ef6b5c"
  coral-on-ink: "#f4a08f"
  ws-canvas: "#f3f4f6"
  ws-surface: "#ffffff"
  ws-border: "#e5e7eb"
  ws-text: "#111827"
  ws-text-muted: "#6b7280"
  ws-ink-button: "#111827"
  ws-indigo: "#6366f1"
  ws-indigo-strong: "#4f46e5"
typography:
  display:
    fontFamily: "'Playfair Display', 'Noto Serif Devanagari', Georgia, serif"
    fontSize: "3.75rem"
    fontWeight: 700
    lineHeight: 1.08
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "'Playfair Display', 'Noto Serif Devanagari', Georgia, serif"
    fontSize: "1.875rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "'Playfair Display', 'Noto Serif Devanagari', Georgia, serif"
    fontSize: "1.125rem"
    fontWeight: 700
    lineHeight: 1.375
    letterSpacing: "-0.01em"
  body:
    fontFamily: "'Inter', 'Noto Sans Devanagari', sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.625
  article-body:
    fontFamily: "Georgia, 'Noto Serif Devanagari', serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.7
  label:
    fontFamily: "'Space Mono', 'Noto Sans Devanagari', monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    letterSpacing: "0.1em"
  section-label:
    fontFamily: "'Space Mono', 'Noto Sans Devanagari', monospace"
    fontSize: "0.65rem"
    fontWeight: 700
    letterSpacing: "0.15em"
  ws-body:
    fontFamily: "ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  none: "0px"
  pill: "9999px"
  ws-control: "0.5rem"
  ws-input: "0.875rem"
  ws-card: "1rem"
spacing:
  gutter: "24px"
  card-pad: "20px"
  section-y: "48px"
  container: "1280px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "12px 24px"
  button-primary-hover:
    backgroundColor: "{colors.press-red}"
    textColor: "{colors.paper}"
  button-cover:
    backgroundColor: "{colors.press-red}"
    textColor: "{colors.card-white}"
    rounded: "{rounded.none}"
    padding: "14px 24px"
  button-cover-hover:
    backgroundColor: "{colors.press-red-deep}"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "6px 12px"
  card-story:
    backgroundColor: "{colors.card-white}"
    rounded: "{rounded.none}"
    padding: "{spacing.card-pad}"
  input-field:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "8px 12px"
  chip-topic:
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "6px 16px 6px 6px"
  ws-button-primary:
    backgroundColor: "{colors.ws-ink-button}"
    textColor: "{colors.ws-surface}"
    rounded: "{rounded.ws-control}"
    padding: "8px 16px"
  ws-button-accent:
    backgroundColor: "{colors.ws-indigo-strong}"
    textColor: "{colors.ws-surface}"
    rounded: "{rounded.ws-control}"
    padding: "8px 16px"
  ws-card:
    backgroundColor: "{colors.ws-surface}"
    rounded: "{rounded.ws-card}"
    padding: "{spacing.card-pad}"
  ws-input:
    backgroundColor: "{colors.ws-surface}"
    textColor: "{colors.ws-text}"
    rounded: "{rounded.ws-input}"
    padding: "12px 16px"
---

# Design System: Ajna Health Lens

## Overview

**Creative North Star: "The Broadsheet Lens"**

The public site is a serious printed newspaper, sharpened for screens. It's ink on clean white paper, with light hairline rules dividing the page the way column rules divide a broadsheet: clear spacing and placement do the structural work, not heavy lines (November 2026, modelled on the clarity of large international news sites). One press red marks what matters right now. Headlines are set in a high-contrast serif (Playfair Display). Small typewriter capitals (Space Mono) carry the newsroom's bookkeeping: sections, dates, "ALL NEWS →". Body text is a quiet sans (Inter). Corners are square everywhere a reader looks. The authority comes from typesetting, not ornament.

Density is a newspaper's, not an app's. Each front-page band has one clear lead, and the rest is ranked beneath or beside it. Whitespace and hairline rules separate sections, not floating cards or heavy rules. Cards are open: picture on top, text under it, no frame. The site is Nepali first, so every type decision has to work in Devanagari as well as Latin script. Each stack names a matched Noto Devanagari face, and Nepali text drops the tracking and italics that Devanagari can't take.

The **editorial workspace** (`/manage/`, `templates/admin_dashboard/`) is a second, deliberately separate system: a calm, rounded, light-grey tool with one indigo accent, built for long working sessions. The code says outright that the two "are not meant to match". Each system is documented on its own terms below. Never borrow parts from one for the other.

**Key Characteristics:**
- Ink, paper and one red, with almost no other hues on the public site.
- Square corners. The only round shapes are topic pills and byline avatars.
- Hairlines as structure: a 1px rule-grey hairline under every section heading and between entries. No 2px ink rules.
- Three voices: a serif for headlines, a typewriter face for labels, a sans for reading.
- Devanagari is a first-class script, not a fallback.

## Colors

The public palette is a newspaper's: warm off-white paper, near-black ink, stone greys for structure, and a single press red.

### Primary
- **Press Red** (`press-red`): the only accent. Section labels, article-type labels when a story isn't plain news (plain news carries no type label), the active nav item, trending rank numbers, link hover, error messages, the cover-story button. Its darker hover state is **Deep Press Red** (`press-red-deep`).
- **Press Red on Ink** (`press-red-on-ink`): the same red, lightened for text on ink sections (standard red is only 3.5:1 there; this is about 6:1). `input.css` applies it automatically to `.text-accent` inside `.bg-foreground`.
- **Coral on Ink** (`coral-on-ink`): the second part of the cover headline's two-tone split. Use it only on ink, as solid colour.

### Neutral
- **Ink** (`ink`): text, primary buttons, the top strip, the cover and video bands. Ink is also the system's only dark surface.
- **Paper** (`paper`, white): the page background and the footer. Text on ink stays the warm `#fafaf8` (`primary-foreground`).
- **Newsprint** (`newsprint`): quiet fills: table headers, inline code, side panels, image placeholders. Homepage bands no longer alternate; they are all white.
- **Card White** (`card-white`): fields and dialogs. Story, course and issue cards no longer have a fill or frame.
- **Rule Grey** (`rule-grey`): 1px hairlines, input borders, table cells.
- **Muted Stone** (`muted-stone`): quiet fills behind loading images.
- **Graphite** (`graphite`): secondary text such as summaries, metadata and captions.

### Workspace palette
- **Workspace Canvas** (`ws-canvas`) behind a **White Surface** (`ws-surface`) shell. Borders are **Workspace Border** (`ws-border`), text is **Workspace Text** (`ws-text`), secondary text is **Workspace Muted** (`ws-text-muted`).
- **Workspace Indigo** (`ws-indigo`): focus rings and the active search field. **Strong Indigo** (`ws-indigo-strong`) fills accent buttons.
- **Status tints** (Tailwind's 50/100 backgrounds with 700 text, in rounded-full pills): sky for in review, emerald for ready or published, amber for pending, red for destructive or error, indigo for pitches.

### Named Rules
**The One Red Rule.** The public site has exactly one accent hue. If a second colour seems needed for meaning, use weight, size or a rule instead.

**The Ink Is the Only Night Rule.** Every dark surface on the public site is Ink. That covers the homepage cover band, the top strip, the video band and page heroes. The footer is white (November 2026). Navy (`#0b1322`, `#1f2a44`) was retired in October 2026. Don't introduce other dark tints or dark gradients.

## Typography

**Display Font:** Playfair Display (with Noto Serif Devanagari, Georgia)
**Body Font:** Inter (with Noto Sans Devanagari)
**Label/Mono Font:** Space Mono (with Noto Sans Devanagari)
**Long-form Article Font:** Georgia (with Noto Serif Devanagari)

**Character:** A high-contrast newspaper serif for headlines against a neutral grotesque for reading. Space Mono adds the typewriter bookkeeping of a newsroom. Everything is self-hosted (`static/css/fonts.css`), so no visitor IP goes to Google.

### Hierarchy
- **Display** (700, 3.75rem desktop / 2.25rem phone, 1.08 line-height, -0.02em): the homepage cover headline only, balanced wrapping.
- **Headline** (700, 1.875rem desktop / 1.5rem phone, -0.02em): section headings ("Latest News", "From the Journal"), page titles, the lead story.
- **Title** (700, 1.125rem, 1.375 line-height, -0.01em): card and list headlines. Underlined on hover, never recoloured as the only hover cue.
- **Body** (400, 0.875–1rem, 1.625 line-height): summaries, descriptions, UI copy. Graphite for secondary text.
- **Article Body** (400, 1.0625rem × reader scale, 1.7 line-height; 1.9 in Nepali): full-text articles. The reader scale defaults to 1.125 (about 19px), and body text fills the article's 7/12 column (~699px at 1280, about 36.5em) so no empty strip sits before the sidebar rule. The cap, `min(76ch, 40em)`, only bites at the smaller A− sizes. `ch` alone is a Latin digit's width and lets too many Nepali characters onto a line, hence the `em` term. A reader's chosen size is stored only when they press A−/A/A+ (`ahl:reader-text-scale-v2`). In-body `h2`s have no rule above them; space separates them. In Nepali, body `h2` is 1.75rem and `h3` 1.125rem bold: Devanagari's tall matra made 1.5 vs 1.15rem read as the same size.
- **Label** (Space Mono 400, 0.75rem, 0.1em tracking, UPPERCASE in Latin): nav, buttons, "ALL NEWS →", dates, metadata.
- **Section Label** (Space Mono 700, 0.65rem, 0.15em tracking, uppercase): article-type tags on cards and small band headings ("TRENDING THIS WEEK").

### Named Rules
**The Devanagari Parity Rule.** Every font stack names a Noto Devanagari face matching the Latin face's style. Under `:lang(ne)`, drop letter-spacing (it breaks the shirorekha, the headline bar), make italics upright, set Space Mono labels in Noto Sans Devanagari at about 20% larger, loosen tight line-heights to 1.45, and turn off drop caps. Every piece of editor- or reader-supplied text (titles, summaries, issue names, course fields, video titles) carries `lang="{{ text|content_lang }}"`, so an English summary on a Nepali page is voiced in English and keeps its Latin styling. Plate initials take the whole first letter, vowel signs and conjuncts included (`plate_initial`).

**The Heading Speaks Alone Rule.** A section heading carries itself. Don't stack a small label above it that repeats it ("NEWS" over "Latest News"). When a section needs context, add a one-line dek in body text under the heading.

## Layout

A single centred column, at most 1280px wide with 24px gutters (16px in the header on phones), runs down the page as a stack of full-width bands. Bands are white, with ink kept for the cover and video bands. Each section heading sits on a 1px hairline with the "see all" link right-aligned on the same baseline, 24px above the content. Every band uses 48px vertical padding. Grids are 3 columns from `md` (1 on phones) with 24px gaps. The front page uses a 12-column split: a 7-column lead story beside a 5-column ranked list, stacking on phones. Section padding is 48px vertically. The header is sticky: its tall brand row collapses on scroll from 768px up, leaving the nav row as a compact menubar.

Every public page shares one edge: `max-w-7xl mx-auto px-6` (1280px, 24px gutters), so the header, catalog pages, article page and footer all line up at the same x. Narrower measures (forms, corrections, legal text) sit inside that edge on purpose; don't introduce `max-w-6xl` page containers. Grids of open cards use `gap-x-8 gap-y-12`: without frames, the 48px row gap is what separates one row's byline from the next row's picture. A wide featured item (section lead, latest issue, featured course) is an open two-column split, `md:gap-x-10`, closed by a hairline before the grid, with its summary capped at 34em. A band whose item count varies (Opinion) sets its columns from the count rather than leaving empty columns. At the foot of an article, topics, citation and the error report form one group separated by space; only references and comments get a hairline.

Breakpoints are Tailwind's defaults (640, 768, 1024, 1280). Horizontal scrollers (topic pills) must be positioning containers, so absolutely positioned screen-reader text can't escape the clip and widen the page.

The workspace is an app shell: a 288px white sidebar beside the content, set inside a rounded, bordered frame on a grey canvas from `lg` up. On phones the sidebar is an off-canvas drawer.

## Elevation & Depth

The public site is flat. Depth comes from whitespace, hairlines and the ink bands, not shadows. Cards don't lift on hover; the headline underline and a slight image zoom are the hover cue. Dropdowns and the cookie dialog carry a soft large shadow because they float over content.

### Shadow Vocabulary
- **Float** (Tailwind `shadow-lg`): dropdowns and menus only.
- No coloured glows: topic pills answer hover by filling red, without lifting or casting a shadow (retired October 2026).
- **Workspace rest** (`shadow-sm`): the workspace shell frame.

Headlines (`h1`–`h3`) wrap with `text-wrap: balance` site-wide, so no headline leaves one word on its last line; an inline `text-wrap` style overrides it, so don't set `pretty` on a headline. The `hidden` attribute always wins over display utilities (`[hidden] { display: none !important; }` in `input.css`), so scripts can toggle it on any styled element.

### Named Rules
**The Flat-at-Rest Rule.** Nothing on the public site casts a shadow until the reader acts on it.

## Shapes

Square corners are the public site's signature: cards, buttons, inputs, images, ad slots, banners and dialogs all have 0px corners. Two shapes are round on purpose: topic pills (fully rounded chips with a red "#" disc) and byline avatars. Hairlines do the structural work, and only that work. A 1px ink rule is kept only where the line means something: the paywall notice and a receipt's total row.

### Named Rules
**The Rule Budget (November 2026).** A line has to mean something. If every edge is ruled, none of them is. A 1px rule-grey line is allowed in exactly these places:
- under a section heading (the section heading component);
- between entries in a ranked or dense list (Trending, Latest News, syllabus, FAQ, policy list, account lists), with no cap rule above the first entry when a label or heading already opens the list;
- one structural edge per region: the header's foot, the brand row, the footer's top and its legal row, the article sidebar's column rule (a top rule on phones), the byline row;
- inputs, tables, and a printable document such as the receipt.

Everything else uses another tool:
- **Grouping** uses space. Never put a rule and a large gap on the same edge. Sidebar blocks are 48px apart with no rule between them.
- **Small labels** (story flags, peer-reviewed, source counts) are typewriter text separated by a middle dot, never boxed.
- **Panels and notices** (gift link, corrections, account access card, org figures, contact, course outcomes, success messages) are a newsprint fill with no border. One notice style everywhere; a coloured left edge bar is banned. Only errors keep a frame: a press-red border on a red tint.
- **Secondary controls** (share, cite, save, gift, text size) are newsprint fills that turn ink on hover, not grey frames. The outline button (1px ink) stays for a single secondary action beside a primary one.
- **Framed cards** are limited to the training enrollment card, the one purchase object on its page.

The workspace is the opposite: gently rounded everywhere. Controls are 8px (`rounded-lg`), inputs 14px, cards 16px (`rounded-2xl`), and status badges fully rounded.

### Named Rules
**The Square Press Rule.** If a reader-facing element has a rounded corner and it isn't a topic pill or avatar, it's a bug.

## Components

### Buttons
Typeset rather than drawn: flat colour fields with typewriter capitals.
- **Shape:** square (0px).
- **Primary:** ink field, paper text, Space Mono label with wide tracking, 12px × 24px padding. Turns press red on hover ("PITCH A STORY →", "SUBSCRIBE").
- **Cover:** press red field, white Inter semibold, 14px × 24px, used on the homepage cover. Darkens to deep press red on hover, and its arrow icon slides 4px right.
- **Outline:** 1px ink border, ink label, fills ink with paper text on hover ("REGISTER").
- **Text link:** Space Mono label with a 1px ink underline border; turns red on hover ("ALL NEWS →", "EDITORIAL POLICY →").
- **Focus:** a visible 2px outline offset from the button. White on ink surfaces, ink on paper.

### Chips (Topic Pills)
The one soft object in a square world (`.topic-pill`, `articles/includes/topic_pill.html`). The pill shows the topic's own name ("मानसिक स्वास्थ्य", "Type 2 Diabetes") beside its "#" disc, never the underscored hashtag form; that form (`hashtag` filter) is for topic-page headings and social copy.
- **Style:** fully rounded, a faint red-to-amber tint, a hairline red border, a red "#" disc, an optional tabular count badge. Three sizes (sm on cards, md, lg on topic pages).
- **State:** on hover it fills press red with white text. The **hot** variant (top three trending) swaps the hairline for an ink outline; no solid ink fill.

### Cards / Containers
- **Corner Style:** square.
- **Open cards:** no fill, no border, no shadow. Image on top at 16:9, text 16px below it, with a 3% image zoom and a headline underline on hover. Columns in a grid of open cards are split by the gutter, not a hairline (From the Journal, Opinion; Nov 2026). Without an image, a Press Plate (below).

### Inputs / Fields
- **Style:** 1px rule grey border, transparent background, square, 8px × 12px, 0.875rem text. Search fields use the Label (mono) face.
- **Focus:** a 2px ink ring (`box-shadow: 0 0 0 2px ink`) with the outline suppressed.
- **Error:** a press-red tinted message strip with a red border, in the label face.

### Navigation
- **Masthead:** the centred serif wordmark "AJNA HEALTH LENS" with the tagline in spaced mono capitals underneath. Search on the left, language switch and account on the right. Above it, an ink strip shows the latest issue and the ISSN.
- **Section nav:** centred row of mono labels (0.65rem, wide tracking) with 2px bottom borders. The active item gets a press red border and text; hover is red text.
- **Below 1024px (phones and tablets):** hamburger, wordmark and search icon; the menu drops down as a full-width paper panel of mono labels. The nine-item Devanagari nav only fits on one row from 1024px, so the full header starts there. From 768px the square SUBSCRIBE button stays in the header too (the phone dock carries it below that). Small controls get a 44px hit area through an invisible `::after`, never by growing the visible control.
- **Phone dock:** the fixed foot-of-screen stack (subscribe bar over the anchor ad) stays hidden until the reader is ~40% down the page and whenever the cookie banner is open, then stays once shown. Without JavaScript it shows as before. Owner-approved ad behaviour (Nov 2026); change it only with their go-ahead.

### Section Heading (signature)
`includes/section_heading.html`: a headline-size serif title, an optional one-line dek in graphite body text, a right-aligned mono "see all" link, and a 1px hairline underneath with 24px below. It's the backbone of every homepage band and catalog page.

### Ranked List (signature)
Used for "Trending this week" and the Latest News column: entries separated by 1px rule-grey hairlines. Trending entries lead with large serif press-red numerals. News entries pair an article-type label, a serif title and metadata with a 4:3 thumbnail on the right.

### Press Plate (signature)
The cover for anything without a picture: stories, issues and training courses (`articles/includes/press_plate.html`, used by `issue_cover.html` and `course_cover.html`). A missing image reads as typesetting rather than an empty box.
- **Composition:** a halftone dot screen (7px pitch, about 22% opacity) fading in from the bottom right. The headline's first letter is set huge in the display serif and cropped by the right and bottom edges. A 2.5rem press-red rule with a stamp in spaced mono capitals sits top left: the masthead for stories, the publication month for issues, "TRAINING" for courses.
- **Plates:** paper with an ink letter, ink with a paper letter (red-on-ink rule), or newsprint with a 1.5px outlined letter. The article id picks the plate, so a story always gets the same one and neighbours differ.
- **Scale:** sized with container units, so one plate works from a 21:9 strip down to a 96px thumbnail. A **quiet** plate (smaller letter, about 70% of the height) is used wherever the plate sits beside a headline that must lead: the picture-less lead strip and course covers. When the newest Latest News story has no picture, the lead becomes a text lead: the plate shrinks to a 21:9 strip and the headline steps up a size. Recency wins over pictures. The stamp drops out below 220px wide.
- **Script:** the initial carries its own `lang`. Devanagari gets a larger size, a lift and a wider right inset so the headline bar stays inside the frame.
- **Motion:** inside a hovered card the letter drifts up and left over 600ms (ease-out-expo), like a plate seating in the press. No motion under reduced motion.

**The No Empty Frame Rule.** Anything without a picture gets a Press Plate, never a flat grey box, a decorative gradient or a stock photo.

### Article Page
Set like a news site's story page: section label, headline, summary (capped at 34em), then the featured picture or video at the reading column's width (3:2, full-bleed on phones, caption under it), then the byline row between hairlines. At most four topic pills sit under the headline, with "+N" linking to the full list at the foot. Share buttons are unframed 36px squares with drawn stroke icons that fill newsprint on hover, (never letter abbreviations) on desktop. On phones the share row is the system share sheet where the browser has one (plus Copy link), else WhatsApp, Facebook and Copy link, 44px tall. On phones a collapsed "In this article (N)" list sits right after the byline and tools rows; the sidebar copy is desktop-only. "Cite this article" is a disclosure. The page ends article → topics/cite/report → related reading → comments, so the last beat is what to read next, not a form. References are set in the body serif. Notices (gift link, gifted-to-you, free-read count, corrections) are a newsprint box with no border, never a coloured edge bar. The sidebar's blocks (contents, author, trending, PDF) are separated by space under the one column rule.

### Paywall Notice
Set as a notice in the paper, never a floating card: a 1px ink rule, a lock and a typewriter label ("Subscription Required", "Single purchase", "Archive Access Required"), one sentence on what is locked, and the price — this article's own price when it is sold singly, and "Subscriptions from Rs. X a month" from the cheapest active monthly plan. One red primary button (SUBSCRIBE, or BUY FOR Rs. X with SUBSCRIBE as the outline secondary), the same for logged-in and logged-out readers; a logged-out reader also gets "Already a subscriber? Log in". No shadow. Metering never spends a free read on an article with nothing behind the paywall.
Above the notice the public abstract stays visible, and the text-size controls are hidden while the body is locked. The notice says what the price buys ("The full article: N min read · N references", counted from the whole body) and closes with one reassurance line: a single purchase stays in the reader's account with an emailed receipt; a subscription never renews by itself and is refundable within SUBSCRIPTION_CANCEL_DAYS. An article with nothing behind the paywall (no text, video or PDF) is never put on sale; it says the full text hasn't been added yet.

### Rate Card (pricing)
/subscribe/ is set like a newspaper's subscription notice, not a SaaS tier grid: one block between hairlines, plans as columns split by hairlines (stacked with hairlines on phones), no card borders, no lift, no hover shadow, no eyebrow above the plan name. Each column: the name (linking to the plan page), the description, the price as the column's headline, the exact VAT-inclusive total and period, the "N months for the price of M" line when real prices show a saving, and one button. The pick carries a mono "OUR PICK" label underlined in press red beside its name, and only its button is red. Features appear once, in the comparison table below, whose label column stays pinned while the plan columns scroll on phones.

### Form Fields
Inputs take a 1px border in `input-border` (#8f8a82, 3.3:1 on paper) rather than the lighter rule colour, so a field reads as a field. Placeholders use muted ink (5.3:1) and are examples, never labels; every field has a label, visually hidden where the design has none.

### Cover Slider (signature)
The homepage hero: an ink band tinted by a blurred copy of the story's own picture, with the photo masked so it melts into the band (right side on wide screens, top on phones). Display headline with an optional coral second half, a cover button, and a byline with article type, date and read time. When there is more than one top story, an ink rail along the foot of the band carries **cover lines**: every top story as a mono number over a two-line serif headline, with a 2px rule above each. They are the slide control (the current line is white with a press-red rule; the rest are paper at 60%), plus a square pause button on pointer screens. Wide screens give each line an equal column; phones scroll them sideways with a peek. Without JavaScript the rail stays hidden and the slides simply stack.
- **Motion:** when the story changes (never on first load) the band fades in over 300ms and the headline is inked left to right with a clip-path over 600ms (ease-out-expo), like a roller passing over the plate. While autoplay runs, the current cover line's rule fills over the 7s interval; it clears while paused, hovered or focused. Reduced motion keeps the fade and drops the roll. Autoplay is off for reduced-motion readers and on touch screens, where the reader swipes or taps a line instead.

### Workspace Components
- **Shell:** white rounded-16px frame on the grey canvas; sidebar groups under small uppercase grey headings.
- **Sidebar item:** 8px-rounded row with a 16px stroke icon. The active row is grey-100 with medium-weight text. Pending-work counts sit in right-aligned status-tint pills.
- **Card:** white, 16px corners, 1px grey-100 border, 20–24px padding, no shadow.
- **Primary button:** gray-900 field, white semibold, 8–12px corners. **Accent button:** indigo-600, darkening to indigo-700. Corner radius currently varies between `rounded-md`, `rounded-lg` and `rounded-xl` across screens; prefer `rounded-lg`.
- **Input:** white, 1px grey border, 14px corners, 12px × 16px padding. Focus gives an indigo border with a 4px indigo-12% halo.
- **Icon action:** 28px square icon button for table row actions. Grey, with hover tints for neutral, danger (red) and success (green).

## Do's and Don'ts

### Do:
- **Do** keep every reader-facing corner square (0px), apart from topic pills and avatars.
- **Do** put a 1px hairline under each section heading and between ranked-list entries, and nowhere the Rule Budget doesn't list; let spacing, not rules, separate groups.
- **Do** use press red as the only accent, and switch to press-red-on-ink for red text on ink surfaces.
- **Do** give each front-page band one lead item and rank the rest; vary the scale between lead and supporting items.
- **Do** name a matched Noto Devanagari face in every new font stack, and test every headline and label in Nepali.
- **Do** give every imageless story, issue and course a Press Plate instead of a grey box or gradient.
- **Do** underline headlines on hover (1–2px, offset 3–6px) as the hover cue, not colour alone.
- **Do** use the workspace's own rounded, indigo system on every `/manage/` screen.

### Don't:
- **Don't** use any dark surface or dark gradient on the public site other than ink.
- **Don't** use gradient text, gradient buttons or rounded pill buttons on the public site.
- **Don't** stack a small label above a section heading that only repeats it.
- **Don't** add shadows to public elements at rest, or frame story cards, chips, labels, notices or panels in boxes.
- **Don't** bring back 2px ink rules or an ink footer.
- **Don't** letter-space or italicise Devanagari text.
- **Don't** bring public-site parts (square corners, Space Mono labels, press red) into the workspace, or workspace parts (rounded cards, indigo) onto the public site.
- **Don't** draw a replacement logo. The confirmed mark is `static/images/logo.png`.
