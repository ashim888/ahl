# Ajna Health Lens — User Tutorial

A practical, task-oriented guide to using the platform: the public health-news site and the
editorial team workspace behind it. For architecture/implementation details, see
`ARCHITECTURE.md`; for what's built vs. planned, see `ROADMAP.md`.

> **Homepage:** the site's main page is `/`. The old preview address `/index/` still works — it
> redirects to `/`.

---

## 1. Who this guide is for

The platform has six account roles, each with progressively more access:

| Role | Can do |
|---|---|
| **Unverified** | Read free content, comment, subscribe to the newsletter, pitch a story, enroll in training |
| **Verified Author** | Everything above, plus a public author page listing their published articles |
| **Reviewer** | Reserved for a future peer-review integration — not active in the current workflow |
| **Editor** | Full editorial workspace access: articles, issues, pitches, ads, newsletter, training, editorial board, comments |
| **Editor-in-Chief** | Everything an Editor can do, plus user verification, subscription/purchase grants, staff role changes |
| **Admin** | Everything, plus creating other Staff/Admin accounts and granting the Admin role itself |

Jump to the section that matches what you're trying to do:

- [§2 — Reading the site](#2-reading-the-site) (anyone)
- [§3 — Creating an account & getting verified](#3-creating-an-account--getting-verified)
- [§4 — Pitching a story](#4-pitching-a-story) (any signed-in account)
- [§5 — The editorial dashboard](#5-the-editorial-dashboard) (Editor and above)
- [§6 — Managing articles](#6-managing-articles) (Editor and above)
- [§7 — Managing issues](#7-managing-issues) (Editor and above)
- [§8 — Managing sections (site navigation)](#8-managing-sections-site-navigation) (Editor and above)
- [§9 — The pitch queue](#9-the-pitch-queue) (Editor and above)
- [§10 — The editorial board page](#10-the-editorial-board-page) (Editor and above)
- [§11 — Training programs](#11-training-programs) (Editor and above)
- [§12 — Ads](#12-ads) (Editor and above)
- [§13 — Newsletter](#13-newsletter) (Editor and above)
- [§14 — Comment moderation](#14-comment-moderation) (Editor and above)
- [§15 — Verification queue](#15-verification-queue) (Editor-in-Chief, Admin)
- [§16 — Subscriptions & purchases](#16-subscriptions--purchases) (Editor-in-Chief, Admin)
- [§17 — Staff accounts & permissions](#17-staff-accounts--permissions) (Editor-in-Chief, Admin)
- [§18 — Running the site: email, worker, analytics clean-up](#18-running-the-site-email-worker-analytics-clean-up) (whoever deploys it)

---

## 2. Reading the site

No account needed for any of this.

- **Browse articles** at `/articles/` — filter by type using the dropdown, or click a keyword
  pill on any article to see everything tagged with it.
- **Search** from the box in the header, or go to `/search/` directly. Search matches title,
  summary, article text, keywords, section and author names — short medical acronyms (e.g. "TB",
  "HIV") and Nepali words work too. Typing in the header box suggests matching headlines and topics.
  Results put title matches first, show the matching sentence with the words highlighted, and can
  be narrowed by **section**, **story type** and **when** (past week/month/year), or sorted newest
  first. A misspelt search offers "Did you mean …".
- **Corrections** (`/corrections/`, linked in the footer) lists every correction, clarification and
  update made to a published story, newest first.
- **Browse issues** (curated story trails/coverage series) at `/issues/`.
- **Browse by topic** using the primary nav (e.g. "Policy & Economy" → "Health Insurance (NHIP)")
  or directly at `/sections/<slug>/` — this is the editorial subject taxonomy, separate from an
  article's type/format. Nav labels switch between English and Nepali via the language switcher
  in the header.
- **Switch language.** The switcher in the header changes the whole interface (menus, buttons,
  labels, messages) between English and Nepali. Articles themselves aren't translated — each
  stays in the language it was written in, and Nepali-language articles automatically get
  Nepali-friendly typography.
- **Read an article.** Free (open-access) articles show full text immediately. Subscription or
  pay-per-article ("special") pieces show the abstract plus a paywall prompt — see §16 for how an
  editor can grant access manually, or use the self-serve checkout links on the article page.
- **Change the text size** — the **A− / A / A+** buttons on the article page make the body text
  smaller or larger (A resets it). Your choice is remembered on that device for every article.
- **Related reading** — the end of each article suggests up to three related articles: the
  editors' picks when they've chosen some, otherwise the most similar articles by topic.
- **Cite an article** — every article page has BibTeX/RIS/plain-text export links.
- **Comment** — sign in to comment immediately, or comment as a guest. After you post, the page
  returns to the comments section with a message: signed-in readers see "Your comment has been
  posted"; guests are told to check their inbox and click the confirmation link, and the
  comment appears only after that click (no CAPTCHA, just email confirmation). You can tick
  "Notify me about follow-up comments" to get an email when someone replies.
- **Subscribe to the newsletter** — the signup box in the footer or homepage works with just an
  email address; you'll get a confirmation link before you're actually subscribed (double
  opt-in), then a short welcome email once you've confirmed. Unsubscribe links in every newsletter email are one-click, no login required.
- **Browse training programs** at `/training/`. Enrolling requires an account (see §3) —
  checkout is currently a stub payment flow (always succeeds; a real gateway isn't wired up yet).
- **Browse subscription plans** at `/subscribe/`.
- **Paying** (subscriptions, special articles, paid courses): once Fonepay is switched on, checkout
  opens a **Pay with Fonepay** page — scan the QR with any bank or wallet app, or on a phone tap your
  bank to open its app and approve. The page confirms automatically and takes you to what you
  bought. If you close it after paying, access is still added within a few minutes. An unpaid
  request expires after 15 minutes; **Try again** starts a new one.
- **About / editorial board / policies** at `/about/editorial-board/` (tabbed: About, Editorial
  Board, Policies).

---

## 3. Creating an account & getting verified

1. Go to `/register/` and sign up with just your name, email and a password (email is your
   login — there's no separate username). You're logged in immediately and taken back to the page
   you came from.
2. New accounts are ordinary reader accounts: you can comment, subscribe, enroll in training and
   pitch stories straight away, and you are **not** put in any review queue. You don't need an
   account at all to be credited on an article: editors credit contributors through author
   profiles, which need no login (see §6).
3. Verification (a **Verified Author** badge) is only for contributors who want their
   credentials shown. Fill in your profile (`/profile/edit/`) with affiliation, bio, ORCID and
   publications, then use **Request verification** on your profile (or `/pending-verification/`).
   Only then is your account added to the queue and the Editor-in-Chief/Admin emailed.
4. An Editor-in-Chief or Admin reviews your request (§15). You'll get an email either way. If
   rejected, you can reapply after 30 days.
5. Once approved, your role becomes **Verified Author**. If your account is linked to an author
   profile, the public author page shows your account's affiliation, bio and photo wherever the
   profile itself leaves them blank.

---

## 4. Pitching a story

Anyone can pitch a story idea — **no account required**, though signing in first means you don't
have to retype your contact info.

1. Go to `/pitches/new/`.
2. Fill in a title, a summary (why this story matters now), and optionally draft body text if
   you already have something written.
3. If you're not signed in, you'll also give your name and email so the editorial team can reach
   you.
4. Submit. You'll get an email whenever the pitch's status changes (moved to review, accepted, or
   rejected).
5. If you have an account, track all your pitches at `/pitches/mine/`, filterable by status.
6. If a pitch is **accepted**, the editorial team turns it into a draft article (see §6). If you
   pitched while signed in, you're added to the byline automatically; otherwise the editors
   credit you by name.

---

## 5. The editorial dashboard

Everything from here down requires an Editor (or higher) account. The dashboard lives at
**`/editorial/`** and every page shares a common sidebar shell.

- **Dashboard home** (`/editorial/`) — KPI cards (published/draft articles, pending
  verifications, active enrollments, active subscriptions with an expiring-soon warning,
  newsletter subscribers, open pitches) and activity charts.
- **Analytics** (`/editorial/analytics/`) — article readership, subscription/ad/newsletter
  trends, cross-domain BI view. Money figures (monthly revenue, purchase totals) show only to an
  Editor-in-Chief or Admin; editors see the counts.
- **Revenue** (`/editorial/revenue/`, Editor-in-Chief/Admin only) — combined training + subscriptions + purchases total, with
  MRR shown separately since it's a forward-looking projection, not money already collected.
  Cross-links to two focused pages: **Training** (`/editorial/revenue/training/`, collected-revenue
  trend) and **Subscriptions** (`/editorial/revenue/subscriptions/`, per-plan active count and
  lifetime revenue, MRR, purchase revenue).
- **Keywords** (`/editorial/keywords/`) — how readers respond to article keywords. See
  "Keyword analytics" below.
- The sidebar shows a **badge count** next to Pitch Queue and Verification Queue whenever there's
  something waiting on you, and next to Comments when new comments were posted in the last 24
  hours — visible from anywhere in the workspace, not just the dashboard home.
- Every list screen in the workspace (articles, pitches, ads, training, staff, newsletter issues,
  purchases, subscriptions) follows the same pattern: a **search box**, one or more **filter
  dropdowns**, and **pagination** — all combined in one form, so changing one doesn't reset the
  others.

### Keyword analytics

Every time an article page is shown, its keyword pills count as **impressions**; every time a
reader clicks one, that's a **click**. **CTR** (click-through rate = clicks ÷ impressions) is the
"urge to click": how often readers who see a keyword actually want more of it. Your own and
other editors' visits are never counted.

On `/editorial/keywords/`:
- Pick a window (**7, 14, 30 or 90 days**; 30 by default), search for a keyword, and sort the
  table by clicks, impressions, CTR, name, number of articles, or followers.
- Keywords with fewer than 20 impressions show their CTR greyed out — too little data to trust —
  and are left out of **Highest reader interest**.
- Charts: impressions and clicks per day, a **heatmap** of when readers click keywords (day of
  week × hour, Nepal time), the top keywords over time, and the most recent clicks.
- **Export CSV** downloads the table for the chosen window.
- Click a keyword for its own page: its daily trend, its click heatmap, where it was clicked
  (top or bottom of the article), and which articles drive its clicks.

---

## 6. Managing articles

`/manage/articles/` — every article regardless of publish status, searchable by title and
filterable by type/status/homepage section.

**Creating an article** (`+ New Article`) — everything is on one page. You write on the left;
the right-hand panel has the buttons and the settings. Fields marked with a red <span>*</span> are
required to publish.
1. **Title** is the only thing needed to save a draft. Add a **Summary** if you want one: one or
   two sentences under the headline and on article cards. Short news pieces can skip it; cards
   then use the opening words of the text (for free articles only, so paid text never leaks).
2. Write the **Article text** in the editor. The toolbar has:
   - **Headings** (Heading / Subheading / Minor heading — the headline itself is the top level),
     bold, italic, underline, strikethrough, sub/superscript, and **Remove format** (cleans up
     text pasted from Word or a website).
   - **Text alignment**: left, centre, right or **justify**.
   - **Bulleted and numbered lists** (the arrow next to each picks the style, e.g. a, b, c or
     i, ii, iii), and **Increase/Decrease indent** for nested points.
   - **Link**, **Upload image**, **Insert media**, **Table**, **Block quote**, **Horizontal
     line**, **Special characters**, inline **Code** and **Code block**, **Find and replace**.
   - **Images:** click Upload image (JPG, PNG, GIF or WebP, up to 5 MB) or use its arrow to
     insert one by URL. Click an image for its toolbar: **alt text** (required: what the
     picture shows — an article can't be published for the first time while an image in the text
     has none), **caption**, **align** left/centre/right (text wraps around left/right
     images; on phones they go full width), **resize** (original, half, three quarters, full
     width) and **link**.
   - **Insert media** takes a YouTube, Vimeo, Dailymotion or Spotify link and embeds the player.
     Other sites' embeds are removed when the article is saved.
   - **Source** shows the raw HTML (e.g. for an embedded chart). Anything the site doesn't
     allow (scripts from unknown sites, iframes from unknown players, styles other than
     alignment/image size) is removed when the article is saved.

   Add **Keywords** (type and press Enter), and **References** under the collapsed "References"
   link if the story cites sources as [1], [2], ….
3. **Save draft** any time — only a title is needed. Drafts also **save automatically** every
   ~20 seconds while you type (the panel shows "Draft saved at …"), and **Ctrl/⌘ + S** saves.
   If you try to leave with unsaved changes, the browser warns you.
4. **Preview** opens the article exactly as readers will see it, in a new tab, without saving.
5. **Publish** puts it on the site (you'll be asked to confirm). Publishing checks the rest: an
   article type, an access type (plus a price for special articles) and article text — or a
   PDF under "More details". If something's missing, the page scrolls to it.
6. In the right-hand panel: **Placement** (article type, menu section, homepage spot, coverage
   series, pin to top), **Access** (Free / Subscribers / Special with its own price),
   **Featured image**, and **Authors** (available once the draft is saved). **More details**
   holds the URL slug, a PDF version, and journal fields (DOI, volume, pages).
7. **Related articles** (the panel under the text): choose the articles to show under "Related
   reading" (the page shows three at most, newest first). A **suggestions** list shows the most
   similar published articles with a **+ Add** button; if you pick nothing, the top suggestions
   are shown automatically. Similarity compares wording, so it only matches articles in the same
   language.

**Review workflow:** a story moves **Draft → In review → Ready to publish → Published** (or
Scheduled). In the right-hand panel:
- **Send for review** (on a draft) — pick an **Assigned editor** in the *Review* card first; they
  get an email with a link to the story. Only a title is needed at this point.
- **Mark ready to publish** (on a story in review) — runs the same checks as Publish, so "ready"
  really means ready.
- **Save (stays in review / stays ready)** keeps the story where it is; **Back to draft** returns it.
- **Publish** and **Schedule** work from any of these steps — for **publishers** only (see below).

**Who can publish:** the Editor-in-Chief and Admins always can. Any other Editor can publish only if
an Editor-in-Chief or Admin ticks **Can publish articles** on their account (Staff → edit; publishers
show a "Publisher" badge in the staff list). Publishing covers: Publish, Schedule, Update live
article, Unpublish/Unschedule, breaking news, public corrections on live stories, restoring a live
story's history, and deleting a live story. Editors without it still write, save, **Send for
review** and **Mark ready** — marking a story ready emails every publisher, and publishers see a
**Ready to publish** link with a count in the sidebar.
- **Internal notes** in the *Review* card are for the team only ("check the 2021 figure with the
  ministry") and never appear on the site. You can delete your own notes; senior staff can delete
  any.
- The sidebar's **Review queue** shows how many stories are waiting in review; the article list
  has an **Assigned → Assigned to me** filter and shows each story's assignee.

**History:** every save is recorded — who, when, what they did (saved, sent for review, published,
updated…) and the words at that point. Open **History** at the bottom of the panel to see the list;
pick a version to see what changed (added words in green, removed in red). **Restore this version**
puts those words back (on a live article, readers see them immediately) — the current words stay in
the history, so a restore can be undone. Background autosaves by the same person within 15 minutes
count as one entry.

**Two people editing the same story:** if someone else saved the article after you opened it, your
save is stopped with a message saying who saved and when — nothing is overwritten. Copy anything you
need, reload the page to get their version, and re-apply your change. Autosave pauses in the same
situation.

**Scheduling:** open **Schedule for later…** under the buttons, pick a date and time (Nepal
time) and click **Schedule**. The same checks as Publish apply. The article then shows as
**Scheduled** (with its go-live time) in the article list and goes live automatically at that
time. To change it, open the article: **Update schedule** saves a new time or edits, **Publish now**
skips the wait, and **Unschedule** moves it back to drafts. If a scheduled article is still waiting
a few minutes past its time, the list marks it "overdue" — that means the background worker isn't
running (see §18).

**Times readers see:** article pages show the publish date and time; cards and lists show
"12 min ago" / "3 hours ago" for the last day, then the date. When you **Update** a live article,
it shows "Updated <time>" under the date — pinning or changing the homepage spot doesn't count as an
update.

**Featured image details:** under the image upload, fill in the **Image description (alt
text)** — what the picture shows, for screen readers and search engines. It's required before an
article with a featured image is first published — plus an optional **Caption** and **Credit** ("Ram Shrestha / Ajna Health Lens"). The
caption and "Photo: <credit>" appear under the image on the article page.

**Corrections & updates:** on a saved article, the **Corrections & updates** panel (right-hand
side) adds a dated note for readers — pick **Correction** (a factual error was fixed),
**Clarification**, or **Update** (new information), write a sentence or two, and click **Add
note**. It appears at the end of the article under "Corrections & updates", with a "Correction
appended ↓" link under the date, and the article is marked "Updated". Fix the article text itself
with **Update live article** as usual — the note is what tells readers it changed. **Remove**
deletes a note added by mistake. Every note also appears on the public **Corrections** page
(`/corrections/`).

**Search & social (optional):** the collapsed **Search & social** card lets you write a different
**search headline** (~60 characters) and **search description** (~155) for Google results and
share cards, with a live Google-style preview, and upload a separate **share image** (1200×630)
for Facebook/X/WhatsApp. Leave them empty and the headline, summary and featured image are used.
The headline on the article page itself never changes.

**Breaking news:** in the *Placement* card, set **Breaking news** to 1–24 hours. Once the story is
live, a red **BREAKING** banner appears under the site header on every page, linking to it (readers
can close it), and the article shows a BREAKING label. It switches itself off when the time is up;
choose **Stop breaking-news banner** to end it early. Only one story is shown at a time — the most
recently published breaking one.

**Editing a published article:** the panel shows **Update live article** instead of Save draft
— your changes go live only when you click it (autosave is off for live articles, so half-typed
edits never appear on the site). **Unpublish** (bottom of the panel) takes it off the site and
back to drafts.

**Video stories:** paste a YouTube link into **Video (YouTube link)**, under the summary. Any
common link works: a watch link, a youtu.be share link, Shorts or live. A thumbnail appears under
the field to confirm the link was recognised.
- The player shows at the top of the story, where the featured image would be. A start time in the
  link (`?t=90`) is kept. The player is YouTube's privacy-enhanced one: no YouTube cookies until
  the reader presses play.
- Pick the article type **Video** for a story that is mainly the video: it can then be published
  without any article text. Any story can carry a video, e.g. a news report with a clip.
- Every story with a video appears on the **Videos** page (`/videos/`, in the main menu) and in
  the **Watch** showcase on the homepage: the 8 latest videos, the first on a large screen and
  the rest in a swipeable reel beneath it. Readers pick a video from the reel and press ▶ to
  watch a free one right there; ▶ on a paid one goes to its subscribe box. To place a video there
  by hand, set *Homepage spot* to **Videos** (the homepage's top story is never repeated in the
  showcase).
- On cards and when shared, a free video story uses YouTube's thumbnail if there's no featured
  image.
- **Subscriber-only videos:** set the access to Subscription or pay-per-article as usual. Readers
  without access see a locked thumbnail pointing to the subscribe box, and the video's address
  isn't shown anywhere on the site. But anyone who gets the link can watch it on YouTube, so
  upload such videos as **Unlisted** on YouTube and add a featured image (YouTube's thumbnail
  isn't used for paid stories).

**Authors:** the **Authors** box on the right of the article form, usable before the first save.
- Start typing in **Search authors** and pick someone from the list (it shows their affiliation and
  whether they have a login). **+ Add me** credits you if you have an author profile.
- Not in the list? Choose **+ Add "…" as a new author** and fill in the **name** (required),
  **affiliation** and **email** (both optional; the email is never shown publicly). Their photo,
  bio and other details can be added later under `/manage/authors/`. The new profile is created
  when the article is saved; if an author with exactly that name already exists, that author is
  credited instead of making a duplicate (unless you enter a different email).
- Add as many authors as needed. Use the ▲/▼ arrows to set the byline order, tick
  **Corresponding author** for the one featured in the author box under the article, and × to
  remove someone. The site shows them as "A, B and C".
- Author changes save with the article (Save draft, autosave, Publish) and appear in the
  article's **History**. On a live article, only people who can publish can change them.
- Every credited author gets a public author page at `/authors/<name>/`, with or without a login
  account.

**After creating an article:**
- **Quick publish/unpublish** — a one-click toggle right from the article list, with a
  confirmation prompt.
- **Delete** — permanent, with a confirmation page. If you just want to stop showing an article,
  unpublish it (set to Draft or Archived) instead.

**Issue assignment**, **Section** (subject-taxonomy placement — see §8, independent of the article
type/format and of homepage curation below), **DOI**, **volume/page numbers**, and **homepage
section** (Hero, Latest News, Opinion, Research Highlights) are all set on the same article form —
homepage placement is editor-curated first, falling back to automatic recency-based fill for any
slot you leave blank.

---

## 7. Managing issues

`/manage/issues/` (linked from the dashboard sidebar as "Issues") — issues are curated story
trails (e.g. ongoing coverage of one topic), not formal journal volumes.

1. Create an issue with a title, optional cover image, and optional editorial note.
2. Attach articles to it from the **article's own edit form** (issue is a field on Article, not
   the other way around) — an issue has no separate "add articles" screen.
3. Toggle **Published** to make it publicly visible at `/issues/`.

---

## 8. Managing sections (site navigation)

`/manage/sections/` — Sections are the subject-taxonomy topics that drive the site's primary
navigation (e.g. "Policy & Economy" with sub-topics like "Health Insurance (NHIP)"), separate from
an article's type (format) and keywords (free tags).

1. Create a **top-level** section (leave Parent blank) for a new nav header, or a **child**
   section (pick a top-level Parent) for a sub-topic under it — only two levels are supported, so
   a child can't have its own children.
2. **Name (English)** and **Name (Nepali)** are both required — the primary nav is bilingual, and
   this is the one place on the site where that's true today (article content itself stays
   single-language). The language switcher in the site header swaps between the two.
3. **Link override**: leave blank for a normal section (it gets its own public landing page at
   `/sections/<slug>/`, listing published articles assigned to it). Set it only for a top-level,
   childless entry that should instead link straight to an existing feature's own page — this is
   how "Training" and "Issues" sit in the same nav list as real content sections without needing
   their own article-aggregation page.
4. **Reorder** using the up/down arrows next to each row, same pattern as the editorial board
   page (§10) — this reorders within the section's own level (top-level sections among
   themselves, or a section's children among each other), not across the whole list.
5. Toggle **Active** to hide a section from the public nav without deleting it — deleting a
   top-level section also deletes its children, and you'll see exactly how many before confirming.
6. To actually place an article in a section, set it on the **article's own edit form** (§6) — same
   pattern as issue assignment, no separate "add articles" screen here either.

---

## 9. The pitch queue

`/manage/pitches/` — defaults to showing only open pitches (Submitted / In Review); use the
status filter to see everything, including already-decided ones.

**Per-pitch actions**, right from the list:
- **Accept** — creates a draft article from the pitch (title, summary, and body copied over) and
  takes you straight to that article's edit page to finish it up. If the pitch has a linked
  account, that person is automatically added as the corresponding author.
- **Reject** — marks it rejected; the submitter gets an email either way.
- **View full details** — opens the full pitch (including any draft body text) plus a feedback
  field, for a closer look before deciding.

**Bulk actions**: check multiple pitches (checkboxes on the left of each row, or "Select all")
and use the **Accept selected** / **Reject selected** buttons at the top — useful for triaging a
busy queue. Already-decided pitches are automatically skipped if accidentally included.

---

## 10. The editorial board page

`/manage/editorial-board/` manages what shows publicly at `/about/editorial-board/` (Board tab).

- Add a member with name, role title, affiliation, bio, and photo. Optionally link it to a real
  user account (useful for board members who also author articles).
- **Reorder** members using the up/down arrows next to each row's order number — this always has
  a visible effect even if several members currently share the same order value.
- Toggle **Active** to control public visibility without deleting the record.

---

## 11. Training programs

`/manage/training/` — manage the courses shown publicly at `/training/`.

**What readers see.** `/training/` is a course catalog: a search box, a **featured course**
banner, topic chips, level/format filters, and a card per course (cover, topic, title,
instructor, level · duration · format, price, start date). Each course page has a summary
header, key facts (level, duration, weekly effort, format, language, certificate), an
enrollment card with price and seats left, **What you'll learn**, **About this course**, **Who
this course is for**, **Prerequisites**, an expandable **Syllabus**, the **Instructor**, **FAQs**,
and **More courses** (same topic first).

**Creating or editing a course** — the form is split into sections:
1. **Basics** — title, a one-line subtitle, *category* (the topic used for filtering — spell it
   the same way across courses so they group together), description, and a cover image
   (landscape, about 1200×675). Without a cover, the page generates one.
2. **Format, schedule & price** — level, format (online / in person / hybrid), language,
   duration, weekly effort, start date (leave empty if learners can start any time), price, an
   optional seat limit, and three switches: *offers certificate*, *is active* (visible to the
   public) and *is featured* (shown as the banner at the top of the catalog).
3. **Outcomes & audience** — *What you'll learn*, *Who this course is for* and *Prerequisites*:
   one item per line, each becomes a bullet.
4. **Syllabus modules** — one row per module: order, title, length (e.g. "Week 1") and a short
   summary. Three blank rows are added each time; leave unused ones empty, and tick *Remove this
   module* to delete one.
5. **Instructor** — name, title/affiliation, bio and photo.
6. **FAQs** — type each question on its own line with the answer on the lines below it, and
   leave a blank line between questions.

**After creating a course:**
- **Enrollments** — click into a course's enrollment list to see who's signed up. You can update
  status/payment status per row, or select multiple rows and apply a status/payment change to
  all of them at once via the bulk toolbar at the top.
- Readers self-enroll from the public course page — you don't create enrollments manually except
  for corrections.

---

## 12. Ads

`/manage/ads/` — house/direct-sold ad creatives, not an ad-network integration.

1. **Create an ad**: pick a zone (each has required pixel dimensions — the cheat-sheet on the
   form highlights the size for whichever zone is currently selected), upload a correctly-sized
   image, sponsor name, link URL, and an optional date range.
2. Ads are **never shown to a subscriber** — ad-free reading is an enforced subscriber perk, not
   just a promise.
3. **"Advertise Here" placeholders**: expand the panel at the top of the ad list to choose, per
   zone, whether an empty (unsold) slot shows a placeholder box instead of just disappearing.
4. **Analytics** (`/manage/ads/analytics/`) — impressions/clicks/CTR, sitewide or filtered to one
   zone, with an independent date-range selector for the chart.
5. **Delete** vs. **deactivate**: deactivating (the toggle button) just stops showing the ad;
   deleting is permanent and also removes its recorded impression/click history.

---

## 13. Newsletter

`/manage/newsletter/` — compose-and-send issues to confirmed subscribers.

1. **Compose** (`+ Compose & Send`): write a subject and body in the same rich-text editor used
   for articles. Starting from scratch? Click **Insert starting template** for a ready-made
   weekly-roundup skeleton (Top Story / Also This Week / From the Editors) instead of a blank
   editor.
2. **Send test to myself** — sends the in-progress issue, exactly as it'll really look (same
   branded template, subject line, and body), to your own account's email address only. Doesn't
   touch subscribers or save anything — use this to check an issue in a real inbox before
   committing to a real send.
3. **Preview** before sending — opens in a new tab showing exactly what a subscriber will
   receive, including the branded header/footer and unsubscribe link. Nothing is sent or saved by
   previewing.
4. **Send** — goes out asynchronously (a background worker, not the request itself), to every
   currently-confirmed subscriber. You'll see a running subscriber count on this screen.
5. The issue list shows each send's status: **Sending…**, **Sent** (with timestamp and recipient
   count), or **Failed** — a failed send shows the error on hover and has a one-click **Retry**
   button.

---

## 14. Comment moderation

`/editorial/comments/` — reader comments post immediately (no pre-moderation queue), so this is
where to remove one after the fact.

- Filter by **Visible** or **Removed**.
- **Remove** a comment to hide it from the article page; **Restore** brings it back. Nothing is
  ever permanently deleted through this screen.
- **New-comment alerts**: the Editor-in-Chief and Admin accounts get an email for every new
  public comment, with the comment text and links to the article and this screen. Comments by
  editorial staff don't trigger it, and a guest's comment triggers it only once they've
  confirmed it by email. The sidebar's **Comments** badge counts comments from the last 24 hours.

---

## 15. Verification queue

Editor-in-Chief and Admin only. `/verification-queue/` — every account with a pending
verification request (from filling out their profile and submitting for review, see §3).

- **Approve** — promotes the account to Verified Author.
- **Reject** — the applicant can reapply after 30 days.
- **View full details** — see their full profile (bio, affiliation, ORCID, publication history)
  before deciding.
- **Bulk approve/reject**: same checkbox-and-toolbar pattern as the pitch queue (§9).

---

## 16. Subscriptions, payments & organizations

Editor-in-Chief and Admin only — this is the money-sensitive tier, one level above general
editorial access.

**Prices and VAT.** Every price you set (plans, special articles, courses) is **VAT-exclusive**.
Checkout adds 13% VAT on top and shows the reader *price + VAT = total*. Every receipt shows the
split. The rate and the business name, PAN and address printed on receipts come from the server's
`.env` (`VAT_RATE`, `BUSINESS_LEGAL_NAME`, `BUSINESS_PAN`, `BUSINESS_ADDRESS`).

**Invoices.** Once `BUSINESS_PAN` is set, receipts are headed **TAX INVOICE**.

- Numbers restart every Nepali fiscal year (from 1 Shrawan): `AHL-2083-84-000001`, and credit notes
  `AHL-CN-2083-84-000001`.
- Readers can add their own **PAN** at checkout (optional, 9 digits) and it's printed on the
  invoice. Organizations' PAN is set on the organization and used for their payments.
- Dates show in both **BS and AD** ("20 Aswin 2083 (6 Oct 2026)"). `INVOICE_DATE_DISPLAY` in `.env`
  switches to `bs` or `ad` only.

- **Plans** (`/manage/billing/plans/`) — create/edit plans (individual monthly, individual
  annual, institutional) and switch them on/off. Institutional plans have no checkout: readers
  see "Ask about your organization" instead, and access comes from **Organizations** below.
- **Payments** (`/manage/billing/payments/`) — every payment: Fonepay checkouts, money recorded
  by staff, organization payments. Each paid one has a numbered **receipt** (click it to view or
  print). Filter by **Failed** to find problems — an underpaid Fonepay payment lands there (the
  reader is emailed to contact you) and never grants access. The Revenue pages add up only
  these payments, **excluding VAT**. VAT collected is shown separately.
- **Subscriptions** (`/manage/billing/subscriptions/`) — every subscription, active or not.
  Filter by **"expiring within 7 days"**. **Grant** one by hand:
  - leave *Amount received* at 0 for a complimentary/press account — no payment, no receipt;
  - for a bank transfer, enter the amount received **including VAT**. It's recorded as a payment
    and the reader is emailed a receipt.
  - A grant to someone who's still subscribed starts the day after their current one ends.
- **Purchases** (`/manage/billing/purchases/`) — special-article unlocks; **Record purchase**
  works the same way (0 = complimentary).
- **Refunds:**
  1. Send the money back first: the Fonepay merchant portal, or a bank transfer.
  2. Open the payment's receipt from **Payments** and use **Record full refund** with a reason.
  - The site removes what the payment bought: the subscription is cancelled, the special article
    locks again, the course enrollment is cancelled.
  - It issues a numbered **credit note** (`AHL-CN-…`) and emails the reader.
  - Refunds are always for the full amount. Revenue leaves refunded payments out and shows the
    refunded total separately.
- **Needs a look** (tick it on **Payments**) — paid, but the payment couldn't be granted
  cleanly. For example, the reader paid twice for an article they already had, or a course
  filled up while they were paying. They're enrolled anyway, since they paid. Refund the extra
  payment or **Mark as handled**.
- **Cancelled within 3 days** — a reader can cancel a subscription themselves from their Billing
  page within 3 days of paying (`SUBSCRIPTION_CANCEL_DAYS`). Their access ends at once and you're
  emailed **Refund to send**. The payment is flagged on **Payments → Needs a look**. Send the
  money back, then **Record full refund** on its receipt as above.
- **Course seats** — someone in the middle of paying holds a seat for up to 15 minutes, so the
  last seat can't be sold twice. An abandoned checkout frees it again.
- **Organizations** (`/manage/billing/organizations/`) — institutional deals. Add the
  organization's **email domains** (e.g. `nhrc.gov.np`; staff at subdomains like
  `dept.nhrc.gov.np` count too), the plan, start/end dates and, optionally, a seat limit.
  - Anyone who **confirms** an email address at one of those domains reads with the
    organization's plan until the end date. Typing the address at sign-up isn't enough. They
    click a link we email them, prompted at sign-up, on the paywall and on their billing page.
  - Public email providers (gmail.com and the like) are refused, since everyone could join.
  - Untick *Active* to stop access straight away.
  - Money received for a deal: enter it (incl. VAT) in *Record a payment received*. The receipt
    goes to the contact email.
  - **Account manager:** pick the staff member who looks after the organization. They're named on
    its dashboard and copied on its usage reports and renewal reminders.
  - The edit page shows this month's usage, the members (with **Make manager**, and anyone the
    organization removed), payments, and **Send last month's report now**.

**What organizations get** — they're the biggest buyers, so they get the most:

- **Their own dashboard** (`/organization/`) for their **managers**. The contact email becomes a
  manager automatically when that person joins; you or another manager can add more.
  - Seats used and left, members who read this month, articles read per month for the last 12
    months, the most-read articles and topics.
  - Each member with how many articles they read and when they last read. **Never which
    articles** — reading about health can reveal something personal.
  - **Remove** someone who left (their seat is freed and they can't rejoin by themselves;
    **Restore** undoes it), **invite colleagues** by work email, download a **CSV**, see
    invoices, the renewal date and their account manager.
- **A monthly usage report**, emailed on the 1st at 07:00 to the contact email and managers,
  with the CSV attached.
- **Renewal reminders** 30 and 7 days before the end date, and once after it ends, to the
  organization and its account manager (or to the Editors-in-Chief and Admins when there's none).
- A read counts once per member, article and day, and only for readers (not staff).

**What readers get:**

- **Billing page** (`/account/billing/`, linked from their profile): current plan and days left,
  **Renew** / **Switch plan**, any renewal already bought, unfinished payments, every payment
  with its receipt, and the articles they own.
- **Renewing early never loses days.** The new period starts the day after the current one ends.
  Subscriptions don't renew automatically (Fonepay payments are one-off). Instead readers get an
  email **7 days** and **1 day** before the end, and one the day after it has ended — unless
  they've already renewed. These go out every morning at 8:00 from the background worker.
- **Receipt email** for every payment, and an email when a Fonepay payment is declined.
- **Back to the story:** subscribing from an article's paywall returns the reader to that article
  after paying.

---

**Terms, privacy and refunds** (`/manage/pages/`, Editor-in-Chief/Admin): three pages at
`/terms/`, `/privacy/` and `/refund-policy/`, covering the whole site, not just payments.

- **Terms of use:** reading and the free-article allowance, accounts, author verification,
  payments, training, organization access, gift links, how our content may be used, the
  health-information disclaimer, editorial standards and corrections, what people send us
  (comments, pitches), community rules, and account suspension.
- **Privacy policy:** what each feature collects (reading, accounts, verification, comments,
  pitches, newsletter, payments, sign-in security), cookies, who it's shared with, how long it's
  kept, and readers' rights.
- **Refunds & cancellations:** stopping free things (newsletter, comment emails, account),
  subscriptions, special articles, training courses, organizations, and how refunds are paid.

They started as **unpublished drafts** written to match how the site actually works.

1. Read them and change anything that isn't your practice, ideally with a lawyer.
2. Tick *Published*. Until then they're hidden: 404 to readers, though you can preview them.

Once published they appear in the footer, and checkout says "By paying you agree to our Terms of
use and Refunds & cancellations". A Nepali version is optional; until it's written, Nepali
readers see the English page.

**Privacy tools** (what readers can do themselves, and what you do on request):

- **Cookie banner** — first-time visitors choose *Accept analytics* or *Only essential*. Google
  Analytics loads only after *Accept*. *Cookie settings* in the footer reopens the choice;
  choosing *Only essential* deletes the analytics cookies.
- **Privacy & your data** (`/account/privacy/`, linked from the profile and footer) — readers
  switch the newsletter, weekly digest and renewal reminders on/off, **download their data** (a
  JSON file), and **delete their account** with their password.
- **Every non-essential email has a one-click unsubscribe** (also the Unsubscribe button Gmail and
  Yahoo show). Receipts and account emails are always sent.
- **Deletion requests by email or letter:** open the account under **Accounts → Edit**, then
  **Delete personal data** at the bottom. Type the account's email to confirm.
  - Staff accounts must be changed to a reader role first.
  - Either way, the profile, files, follows, saved articles, newsletter subscription and sign-in
    history are deleted, and any active subscription ends.
  - Receipts are kept (tax law) and still show who paid. Published comments and bylines stay, as
    "Deleted user"; the reader can choose to remove their comments too.
  - Requests to see or correct data: readers can do both themselves. Otherwise reply within 30
    days, as the privacy policy promises.
- **Consent at sign-up** — once Terms/Privacy are published, new accounts must tick "I agree", and
  the date is recorded.
- **Automatic clean-up** every night (03:30), as the privacy policy says:
  - comment IP addresses after 90 days;
  - sign-in attempt records after 90 days;
  - newsletter sign-ups never confirmed after 30 days;
  - expired sessions.

**Cancelling within 3 days.** On their Billing page, a subscription paid in the last 3 days
shows **Cancel & refund** with the deadline. Cancelling ends access straight away and emails them
a confirmation. You're emailed to send the refund (see Refunds above).

**Reader reports** (**Reports** in the sidebar, any editor; a red count shows open ones):

- Every article has a "Report it" line above the comments, and every comment has **REPORT**.
  Readers choose a reason: error, misleading health information, abuse, private information,
  copyright, spam, or other.
- Senior staff and the contact address are emailed for each report.
- For each report, write what you did (it's kept as the record), then:
  - **Remove the comment & close**;
  - **Action taken** (for example after correcting the article or taking it down);
  - **No action needed**.
- Copyright and privacy reports are highlighted. Act on them promptly, and reply to the reader
  if they left an email.
- Closed reports stay under *Action taken* / *No action needed*, so you can always show what
  was reported and what you did.

**If personal data may have leaked**, follow `INCIDENT_RESPONSE.md` in the code repository: who
to call, what to switch off, who must be told within 72 hours, and how to email the people
affected (`python manage.py notify_users`).

---

## 17. Staff accounts & permissions

Editor-in-Chief and Admin only, with one carve-out noted below.

- **Authors** (`/manage/authors/`) — everyone who can be credited on articles. Any Editor+ can
  use it.
  - **New author** needs only a name. There is no password or login involved. You can add
    affiliation, bio, photo, ORCID and links.
  - **Create user account** (on an author without one) gives them a login when they need to sign
    in. The form is prefilled from the author. The password is optional: leave it empty and
    they're emailed a link to choose their own.
  - **Link an existing account** attaches a login that already exists; **Unlink** detaches it.
    Bylines never change either way.
  - **Deactivate** hides an author from the article form's author search and removes their public page. Their
    existing bylines stay. Authors are never deleted.
  - Filter by *has an account / no account* and active/inactive.
- **Accounts** (`/manage/accounts/`) — reader and author **login** accounts: search, filter by
  role, deactivate/reactivate. **New account** has an optional password (leave it empty to email
  an invite link). Accounts still waiting to set a password are marked *Invited*, with a
  **resend invite** link. **Create author profile** makes an account creditable on articles.
  Any Editor+ can access this screen, but only an Editor-in-Chief or Admin can change an
  account's **login email** (changing it plus a password reset would hand over the account).
- **Staff** (`/manage/staff/`) — manage Editor/Editor-in-Chief/Admin accounts. An Editor-in-Chief
  can create new Editor/EiC accounts but **cannot** grant the Admin role — only an existing Admin
  can create another Admin. An EiC also can't edit, deactivate or change the role of an existing
  Admin; those rows say "Managed by Admins".
- **Change role** (from a user's row) — move any account to any role. Same Admin-granting
  restriction applies: an EiC can promote up to EiC, never to Admin.
- **Two-step sign-in** — every Editor, Editor-in-Chief and Admin signs in with their password
  **and** a 6-digit code from an authenticator app (Google Authenticator, Microsoft
  Authenticator, Authy).
  - The first sign-in after this is switched on asks them to scan a QR code, then shows **10
    backup codes** once. Print them or keep them in a password manager. Each works once.
  - Lost phone: sign in with a backup code, or ask an Editor-in-Chief/Admin to **Reset two-step
    sign-in** on the staff member's edit page (only Admins can reset an Admin). They set it up again
    at their next sign-in. If nobody can sign in: `python manage.py reset_two_step <email>` on
    the server.
  - New backup codes: **Privacy & your data** → *New backup codes*.
  - Every set-up, reset and backup-code sign-in is emailed to the account's owner.
- **Permissions / Groups** (`/manage/permissions/`, `/manage/groups/`) — Django's underlying
  group/permission system, for future-proofing; nothing in the app currently checks group
  membership day-to-day (every screen gates on role, not group).

---

## Tips that apply everywhere in the editorial workspace

- **Search boxes** on manage lists match against the obviously relevant fields for that list
  (article title; pitch title/contact; sponsor name; course title/instructor; staff name/email) —
  type and press Enter or click Search.
- **Confirm dialogs** appear before anything destructive or hard-to-reverse (publish/unpublish,
  deactivate, delete, bulk actions) — read them, they usually say exactly what will happen.
- **Bulk-select toolbars** (pitch queue, verification queue, training enrollments) disable their
  action buttons until you've checked at least one row.
- If you land on a page you don't have access to, you'll see a plain explanation of why (your
  current role) rather than a bare error — with a link back home or a way to request access.

---

## 18. Running the site: email, worker, analytics clean-up

For whoever installs and deploys the site. The settings live in the server's `.env` file —
**restart the app after changing it.** See `README.md` for the full list.

- **Email.** Until SMTP is configured, emails only print to the server console and nobody
  receives them. Set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` plus
  `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL`.
  For port **465** (typical on cPanel) set `EMAIL_USE_SSL=True`; for port **587** set
  `EMAIL_USE_TLS=True` instead.
- **`SITE_BASE_URL`** must be the public address, e.g. `https://ajnahealthlens.com`. Every link
  in every email (comment confirmation, newsletter confirm/unsubscribe, password reset) is
  built from it. `python manage.py check --deploy` flags a `localhost` or non-`https` value.
- **The background worker** (`python manage.py qcluster`) must run all the time, as its own
  service next to the web app. It publishes **scheduled articles** (checked every minute), sends
  newsletters and weekly digests, and runs the daily analytics clean-up. If it isn't running,
  those silently never happen — scheduled articles show as "overdue" in the article list. To
  publish due articles by hand: `python manage.py publish_scheduled`.
- **Analytics clean-up.** Page views, ad impressions/clicks and keyword impressions/clicks older
  than `ANALYTICS_RETENTION_DAYS` (default 400 days) are deleted once a day by the worker. To run
  it by hand: `python manage.py prune_analytics_events` (add `--days 180` to keep less).

**Error pages.** A missing page shows a friendly "We can't find that page" with a search box
already filled in from the address. A server error shows a simple bilingual page. A form left open
too long shows "Please try that again" instead of a bare security error.

**Alerts — know before readers tell you.** Set `ADMIN_EMAILS` (comma-separated) in `.env`.

- Every server error is emailed to them, with the details.
- **Broken links on our own site** (one of our pages linking to a page that doesn't exist) are
  emailed too. Mistyped addresses and bots probing for WordPress files are ignored.
- **Sentry** (optional): set `SENTRY_DSN` to group errors and see trends. Readers' personal data
  isn't sent.
- **`/healthz/`** answers 200 when the database, cache and background worker are fine, and 503
  otherwise — point an uptime monitor (UptimeRobot, Better Stack) at it.
- **Worker and failed-task alerts:** add this to the server's crontab so someone hears when the
  worker stops (a stopped worker can't report itself):

  ```
  */15 * * * * cd /path/to/ahl && .venv/bin/python manage.py check_health
  ```

  It emails `ADMIN_EMAILS` if the worker hasn't checked in for 15 minutes (at most once an hour),
  and once for each background task that failed.

**Emailed backups.** Set `BACKUP_EMAIL` (an address *outside* this server, e.g. a Gmail kept for
backups) and `BACKUP_ENCRYPTION_PASSWORD` (long; keep it somewhere safe — without it a backup
can't be opened).

- Every night at 02:00 the worker emails an encrypted, compressed database dump there.
- Over `BACKUP_EMAIL_MAX_MB` (default 20) it isn't sent and `ADMIN_EMAILS` are told — move to
  server-side backups (`backup.sh`) and off-site storage then.
- Send one now: `python manage.py email_backup`.
- **Restore:** `python manage.py decrypt_backup ajna_health_lens-….sql.gz.enc` (uses
  `BACKUP_ENCRYPTION_PASSWORD` from `.env`, or asks for it, and writes the `.sql.gz` next to it), then
  `gunzip -c ajna_health_lens-….sql.gz | mysql -u <user> -p ajna_health_lens`. Test a restore once, on a
  spare database, before you need it.

**Security headers.** Pages send a Content-Security-Policy listing the outside sites allowed to
run code or show frames (Google Analytics, YouTube/Vimeo/Dailymotion/Spotify embeds, Fonepay,
Cloudflare Turnstile, chart libraries). Adding a new kind of embed or script from another site
means adding it to `CSP_DIRECTIVES` in `settings.py`. Anything blocked is logged as
"CSP violation". Set `CSP_REPORT_ONLY=True` to only report, not block, while testing a change.

**Search index.** Articles are indexed for search as they're saved. After importing articles
straight into the database, run `python manage.py rebuild_search_index`.

