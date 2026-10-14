# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary readers are **health professionals**: doctors, nurses, public-health workers and researchers in Nepal who want credible clinical, research and policy news. The **informed Nepali public** is the second audience. Content is written to a professional standard but must stay readable by a non-specialist. Most stories are in Nepali (site default `ne`), with English as the alternate interface language.

The editorial team is the second user group. Editors, the Editor-in-Chief and admins use the custom dashboard (`/manage/`) to publish articles, manage issues, sections, the editorial board, training, subscriptions, ads, newsletters, reader pitches and user verification. Roles and permissions are in ARCHITECTURE.md §6.

## Product Purpose

Ajna Health Lens is the news and brand side of a peer-reviewed health journal. It has two parts:

1. **Public health news site:** news, commentary, editorials and brand-showcase pieces such as case reports and research briefs, browsable by section and issue.
2. **Editorial workspace:** the team's day-to-day tool for running everything above.

Formal manuscript submission and peer review happen on OJS (Open Journal Systems), outside this platform. This product must never rebuild them.

Success means professionals trust the site as a source, readers subscribe or buy articles, health workers enroll in training and pitch stories, and editors can run the site without developer help.

## Positioning

Three things together, which neither a general Nepali news outlet nor a journal website offers on its own:

- **Journal-backed rigor:** linked to a peer-reviewed journal, with evidence-grounded reporting, numbered references and citation export, and a named editorial board of experts.
- **Depth over speed:** explainers and analysis with full-text articles, data charts and structured article types, not just breaking news.
- **A practitioner community:** training courses, reader story pitches and verified-author profiles, so health workers learn from the site and contribute to it as well as read it.

## Operating Context

- Readers: mostly reading in Nepali; the public site is server-rendered and needs to work on mobile.
- Access tiers: open access, subscription, and pay-per-article. The abstract is always public; full text is gated. Gifting and archival access exist.
- Payments: everything runs through a stub gateway for now. Local providers (eSewa, Khalti, Fonepay, ConnectIPS, CityPay) are under consideration, and none is chosen yet.
- Reader engagement: comments, bookmarks, follows and digests, a newsletter, and keyword follows.
- Editors: work in the custom dashboard, can preview an article before saving it, and use per-article-type content templates.

## Capabilities and Constraints

- Stack: Django 5.x server-rendered templates, Tailwind CSS compiled with the CLI (no Play CDN), and small vanilla-JS enhancements only (no SPA). MySQL in development, MariaDB in production.
- i18n: interface chrome is translated (en/ne); article content is single-language.
- Revenue: house ads only (the `ads` app), plus subscriptions, single-article purchases and training fees.
- Out of scope: manuscript submission, peer review, and APCs (all belong to OJS); dynamic paywalls; mobile apps.
- Undecided: which payment gateway to use.

## Brand Commitments

- Name: **Ajna Health Lens**.
- Tagline (confirmed): **"Illuminating Health Research"**.
- Logo (confirmed, final): `static/images/logo.png`. Note that `templates/base.html` currently has the logo `<img>` commented out, so the masthead shows text only. Future work must use this asset and must not draw a replacement.
- Not confirmed: the ISSN (`0000-0000`) and the publisher name ("Health Lens Publishing") are settings defaults. Treat them as unverified until confirmed, and never present them as fact.
- The Figma Make prototype in `frontend/` (and its `z_*.png` screenshots) was only a starting sketch. The shipped Django templates have replaced it as the incumbent interface, so it is not a design reference. The goal now is a better design than the current templates.

## Evidence on Hand

- A real editorial board, published at `/about/editorial-board/`, comes from the `EditorialBoardMember` data.
- Training courses, issues and articles come from the database. Use real records; never invent sample content to present as published.
- No testimonials, reader counts, partner logos, press mentions or impact metrics have been supplied. Do not fabricate any of these.

## Product Principles

1. **Credibility before reach.** Every surface should signal journal-grade rigor (sources, authors, the board, dates) before it tries to drive engagement.
2. **Professionals set the bar; the public must still follow.** Write and structure for the expert, but never in a way that locks out the informed reader.
3. **Nepali first.** Nepali is the default reading language; English is a full alternative, not an afterthought.
4. **Free, then paid, made clear.** Readers should always know what they can read, why something is gated, and how to get access.
5. **Editors run it themselves.** Workspace tools favour clarity and safe defaults over power-user density.

## Accessibility & Inclusion

No formal standard has been set yet. The bilingual en/ne interface requires typography and layout that work equally well in Devanagari and Latin script.
