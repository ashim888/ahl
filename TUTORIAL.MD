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
  abstract, keywords, and author names — short medical acronyms (e.g. "TB", "HIV") work too.
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
- **About / editorial board / policies** at `/about/editorial-board/` (tabbed: About, Editorial
  Board, Policies).

---

## 3. Creating an account & getting verified

1. Go to `/register/` and sign up with your email (email is your login — there's no separate
   username). You're logged in immediately after registering.
2. New accounts start as **Unverified**. You can already comment, subscribe, enroll in training,
   and pitch stories. Verification marks you as a **Verified Author**. You don't need an account
   at all to be credited on an article: editors credit contributors through author profiles,
   which need no login (see §6).
3. To request verification, fill out your profile (`/profile/edit/`) with your affiliation, bio,
   ORCID, publication history, etc., then submit for review from the "pending verification" page.
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
  trends, cross-domain BI view.
- **Revenue** (`/editorial/revenue/`) — combined training + subscriptions + purchases total, with
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
2. Write the **Article text** in the editor. Use the "Source" toggle if you need raw HTML (e.g.
   an embedded chart). Add **Keywords** (type and press Enter), and **References** under the
   collapsed "References" link if the story cites sources as [1], [2], ….
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

**Editing a published article:** the panel shows **Update live article** instead of Save draft
— your changes go live only when you click it (autosave is off for live articles, so half-typed
edits never appear on the site). **Unpublish** (bottom of the panel) takes it off the site and
back to drafts.

**After creating an article:**
- **Authors** — go to the article's "Authors" screen (a separate step from the article form).
  In each row, **pick an existing author** from the list, or **type a new author's name** (and
  affiliation) to create their author profile on the spot. If an author with exactly that name
  already exists, that author is used instead of making a duplicate. Set the order and mark the
  corresponding author, then **Save authors**. Every credited author gets a public author page
  at `/authors/<name>/`, with or without a login account.
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

## 16. Subscriptions & purchases

Editor-in-Chief and Admin only — this is the money-sensitive tier, one level above general
editorial access.

- **Plans** (`/manage/billing/plans/`) — anyone Editor+ can create/edit subscription plans
  (individual monthly, individual annual, institutional) and toggle them active/inactive.
- **Subscriptions** (`/manage/billing/subscriptions/`) — every grant, active or not, whether from
  a reader's self-serve checkout or manually granted here. Filter by status or plan, or by
  **"expiring within 7 days"** to catch renewals before they lapse. **Grant** a subscription
  manually (e.g. a comp/press account) or **Cancel** an active one.
- **Purchases** (`/manage/billing/purchases/`) — one-time pay-per-article unlocks. Filter by
  article, or **Grant** one manually.

Readers can also self-serve at `/subscribe/` (plans) and from any pay-per-article article page —
both use a stub payment gateway right now (always succeeds; no real charge is made until a real
payment provider is integrated).

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
  - **Deactivate** hides an author from the byline picker and removes their public page. Their
    existing bylines stay. Authors are never deleted.
  - Filter by *has an account / no account* and active/inactive.
- **Accounts** (`/manage/accounts/`) — reader and author **login** accounts: search, filter by
  role, deactivate/reactivate. **New account** has an optional password (leave it empty to email
  an invite link). Accounts still waiting to set a password are marked *Invited*, with a
  **resend invite** link. **Create author profile** makes an account creditable on articles.
  Any Editor+ can access this screen.
- **Staff** (`/manage/staff/`) — manage Editor/Editor-in-Chief/Admin accounts. An Editor-in-Chief
  can create new Editor/EiC accounts but **cannot** grant the Admin role — only an existing Admin
  can create another Admin.
- **Change role** (from a user's row) — move any account to any role. Same Admin-granting
  restriction applies: an EiC can promote up to EiC, never to Admin.
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
  service next to the web app. It sends newsletters and weekly digests and runs the daily
  analytics clean-up. If it isn't running, those silently never happen.
- **Analytics clean-up.** Page views, ad impressions/clicks and keyword impressions/clicks older
  than `ANALYTICS_RETENTION_DAYS` (default 400 days) are deleted once a day by the worker. To run
  it by hand: `python manage.py prune_analytics_events` (add `--days 180` to keep less).
