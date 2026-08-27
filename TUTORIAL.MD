# Ajna Health Lens — User Tutorial

A practical, task-oriented guide to using the platform: the public health-news site and the
editorial team workspace behind it. For architecture/implementation details, see
`ARCHITECTURE.md`; for what's built vs. planned, see `ROADMAP.md`.

> **Note on the homepage:** until launch, `/` shows a "Coming Soon" splash page. The real
> homepage is reachable at **`/index/`** — editorial staff should use that URL to preview the
> live site before the public root is swapped over.

---

## 1. Who this guide is for

The platform has six account roles, each with progressively more access:

| Role | Can do |
|---|---|
| **Unverified** | Read free content, comment, subscribe to the newsletter, pitch a story, enroll in training |
| **Verified Author** | Everything above, plus get bylined on articles and appear on public author pages |
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
- [§8 — The pitch queue](#8-the-pitch-queue) (Editor and above)
- [§9 — The editorial board page](#9-the-editorial-board-page) (Editor and above)
- [§10 — Training programs](#10-training-programs) (Editor and above)
- [§11 — Ads](#11-ads) (Editor and above)
- [§12 — Newsletter](#12-newsletter) (Editor and above)
- [§13 — Comment moderation](#13-comment-moderation) (Editor and above)
- [§14 — Verification queue](#14-verification-queue) (Editor-in-Chief, Admin)
- [§15 — Subscriptions & purchases](#15-subscriptions--purchases) (Editor-in-Chief, Admin)
- [§16 — Staff accounts & permissions](#16-staff-accounts--permissions) (Editor-in-Chief, Admin)

---

## 2. Reading the site

No account needed for any of this.

- **Browse articles** at `/articles/` — filter by type using the dropdown, or click a keyword
  pill on any article to see everything tagged with it.
- **Search** from the box in the header, or go to `/search/` directly. Search matches title,
  abstract, keywords, and author names — short medical acronyms (e.g. "TB", "HIV") work too.
- **Browse issues** (curated story trails/coverage series) at `/issues/`.
- **Read an article.** Free (open-access) articles show full text immediately. Subscription or
  pay-per-article ("special") pieces show the abstract plus a paywall prompt — see §15 for how an
  editor can grant access manually, or use the self-serve checkout links on the article page.
- **Cite an article** — every article page has BibTeX/RIS/plain-text export links.
- **Comment** — sign in to comment immediately, or comment as a guest (you'll get a one-click
  confirmation email before it posts — no CAPTCHA, just email confirmation).
- **Subscribe to the newsletter** — the signup box in the footer or homepage works with just an
  email address; you'll get a confirmation link before you're actually subscribed (double
  opt-in). Unsubscribe links in every newsletter email are one-click, no login required.
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
   and pitch stories — the only thing verification unlocks is a **byline**: appearing as a named
   author on published articles and having a public author page.
3. To request verification, fill out your profile (`/profile/edit/`) with your affiliation, bio,
   ORCID, publication history, etc., then submit for review from the "pending verification" page.
4. An Editor-in-Chief or Admin reviews your request (§14). You'll get an email either way. If
   rejected, you can reapply after 30 days.
5. Once approved, your role becomes **Verified Author** and you can be added as a byline on
   articles.

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
6. If a pitch is **accepted**, the editorial team turns it into a draft article (see §6) and will
   reach out about a byline if you have an account.

---

## 5. The editorial dashboard

Everything from here down requires an Editor (or higher) account. The dashboard lives at
**`/editorial/`** and every page shares a common sidebar shell.

- **Dashboard home** (`/editorial/`) — KPI cards (published/draft articles, pending
  verifications, active enrollments, active subscriptions with an expiring-soon warning,
  newsletter subscribers, open pitches) and activity charts.
- **Analytics** (`/editorial/analytics/`) — article readership, subscription/ad/newsletter
  trends, cross-domain BI view.
- **Revenue** (`/editorial/revenue/`) — training program revenue snapshot.
- The sidebar shows a **badge count** next to Pitch Queue and Verification Queue whenever there's
  something waiting on you, visible from anywhere in the workspace, not just the dashboard home.
- Every list screen in the workspace (articles, pitches, ads, training, staff, newsletter issues,
  purchases, subscriptions) follows the same pattern: a **search box**, one or more **filter
  dropdowns**, and **pagination** — all combined in one form, so changing one doesn't reset the
  others.

---

## 6. Managing articles

`/manage/articles/` — every article regardless of publish status, searchable by title and
filterable by type/status/homepage section.

**Creating an article** (`+ New Article`):
1. Fill in title, abstract, type, and keywords (type-to-add tags — start typing and pick an
   existing keyword or create a new one).
2. Write the body in the rich-text editor. Use the "Source" toggle in the toolbar if you need to
   drop into raw HTML (e.g. an embedded chart). Code blocks are supported with language labels.
3. Click **Preview** any time to see exactly how the article will render publicly, in a new tab —
   including citation links and any embedded chart — without saving.
4. Your work **autosaves** as you type (see the status indicator near the Save buttons), so a
   closed tab or crash won't lose a draft.
5. Choose **Save as Draft** or **Save & Publish**. Draft articles are never publicly visible.
6. **Access tier**: every article is Free (open access), Subscription, or Pay-per-article
   ("special", with its own price) — set this on the article form; it's an editorial call per
   article, not automatic from the article type.

**After creating an article:**
- **Authors** — go to the article's "Authors" screen to add bylines (only Verified Author and
  above can be added), set author order, and mark the corresponding author. This is a separate
  step from the article form itself.
- **Quick publish/unpublish** — a one-click toggle right from the article list, with a
  confirmation prompt.
- **Delete** — permanent, with a confirmation page. If you just want to stop showing an article,
  unpublish it (set to Draft or Archived) instead.

**Issue assignment**, **DOI**, **volume/page numbers**, and **homepage section** (Hero, Latest
News, Opinion, Research Highlights) are all set on the same article form — homepage placement is
editor-curated first, falling back to automatic recency-based fill for any section you leave
blank.

---

## 7. Managing issues

`/manage/issues/` (linked from the dashboard sidebar as "Issues") — issues are curated story
trails (e.g. ongoing coverage of one topic), not formal journal volumes.

1. Create an issue with a title, optional cover image, and optional editorial note.
2. Attach articles to it from the **article's own edit form** (issue is a field on Article, not
   the other way around) — an issue has no separate "add articles" screen.
3. Toggle **Published** to make it publicly visible at `/issues/`.

---

## 8. The pitch queue

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

## 9. The editorial board page

`/manage/editorial-board/` manages what shows publicly at `/about/editorial-board/` (Board tab).

- Add a member with name, role title, affiliation, bio, and photo. Optionally link it to a real
  user account (useful for board members who also author articles).
- **Reorder** members using the up/down arrows next to each row's order number — this always has
  a visible effect even if several members currently share the same order value.
- Toggle **Active** to control public visibility without deleting the record.

---

## 10. Training programs

`/manage/training/` — manage the courses shown publicly at `/training/`.

1. Create a course: title, description, price, duration, instructor, optional syllabus, and an
   optional enrollment cap.
2. **Enrollments** — click into a course's enrollment list to see who's signed up. You can update
   status/payment status per row, or select multiple rows and apply a status/payment change to
   all of them at once via the bulk toolbar at the top.
3. Readers self-enroll from the public course page — you don't create enrollments manually except
   for corrections.

---

## 11. Ads

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

## 12. Newsletter

`/manage/newsletter/` — compose-and-send issues to confirmed subscribers.

1. **Compose** (`+ Compose & Send`): write a subject and HTML body.
2. **Preview** before sending — opens in a new tab showing approximately what a subscriber will
   receive, including the unsubscribe footer. Nothing is sent or saved by previewing.
3. **Send** — goes out asynchronously (a background worker, not the request itself), to every
   currently-confirmed subscriber. You'll see a running subscriber count on this screen.
4. The issue list shows each send's status: **Sending…**, **Sent** (with timestamp and recipient
   count), or **Failed** — a failed send shows the error on hover and has a one-click **Retry**
   button.

---

## 13. Comment moderation

`/editorial/comments/` — reader comments post immediately (no pre-moderation queue), so this is
where to remove one after the fact.

- Filter by **Visible** or **Removed**.
- **Remove** a comment to hide it from the article page; **Restore** brings it back. Nothing is
  ever permanently deleted through this screen.

---

## 14. Verification queue

Editor-in-Chief and Admin only. `/verification-queue/` — every account with a pending
verification request (from filling out their profile and submitting for review, see §3).

- **Approve** — promotes the account to Verified Author.
- **Reject** — the applicant can reapply after 30 days.
- **View full details** — see their full profile (bio, affiliation, ORCID, publication history)
  before deciding.
- **Bulk approve/reject**: same checkbox-and-toolbar pattern as the pitch queue (§8).

---

## 15. Subscriptions & purchases

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

## 16. Staff accounts & permissions

Editor-in-Chief and Admin only, with one carve-out noted below.

- **Authors** (`/manage/authors/`) — manage Unverified/Verified Author accounts: search, filter
  by role, deactivate/reactivate. Any Editor+ can access this screen.
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
