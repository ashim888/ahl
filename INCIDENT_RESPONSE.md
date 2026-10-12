# Data incident response plan

What to do if personal data on Ajna Health Lens may have been exposed, lost or changed by someone who shouldn't have had
it. Examples: a leaked database backup, a stolen staff password, an email sent to the wrong list, a server break-in, or a
bug that showed one reader's data to another.

**Rule one: act quickly and write everything down.** Some laws set short deadlines; GDPR, for example, gives 72 hours to
tell the regulator. You can't meet a deadline you don't know started.

---

## 0. Contacts (fill in and keep current)

| Role | Name | Phone | Email |
|---|---|---|---|
| Incident lead (decides) | | | |
| Deputy (if the lead is unreachable) | | | |
| Technical lead (server, database, code) | | | |
| Lawyer | | | |
| Hosting provider support | | | |
| Fonepay merchant support (payments) | | | |
| Email provider support | | | |

---

## 1. First hour — stop it getting worse

1. **Tell the incident lead.** Anyone who spots a possible incident reports it right away, even if unsure.
2. **Start the incident log** (section 6) and note the time you found out. Deadlines run from then.
3. **Contain** (the technical lead, as far as it applies):
   - A staff account was compromised: deactivate it under **Staff**, then reset its password.
   - Server or database exposure: change the secrets in the server `.env` and restart the app:
     - `SECRET_KEY` (this signs everyone out, and invalidates email-confirmation and unsubscribe links);
     - `DB_PASSWORD`, also changed in MySQL;
     - `EMAIL_HOST_PASSWORD`;
     - `TURNSTILE_SECRET_KEY`;
     - `FONEPAY_PASSWORD` and `FONEPAY_PRIVATE_KEY`. Contact Fonepay to issue new credentials.
   - Sign everyone out without changing `SECRET_KEY`: `python manage.py shell -c "from django.contrib.sessions.models import Session; Session.objects.all().delete()"`.
   - A file was put somewhere public (a backup, an export): remove it and ask the host to purge any copies.
   - An ongoing attack: put the site in maintenance mode, or block the attacker's address at the server or firewall.
4. **Preserve evidence.** Don't wipe the server. Keep the web server logs, the app's error emails (`ADMIN_EMAILS`), the
   sign-in attempt records (Django admin → Axes) and a copy of the database, for the investigation.

## 2. First day — work out what happened

Answer, and record in the log:

- **What happened**, when it started and when it was stopped.
- **Which data**:

  | Data | Where it lives | Sensitivity |
  |---|---|---|
  | Names, emails, scrambled passwords | `users_user` | Medium. Passwords are hashed; still force resets |
  | Author-verification details and CVs | `users_user`, `private_media/` | Higher: CVs hold personal history |
  | Payments, receipts (names, amounts, Fonepay references) | `billing_payment` | Medium. No card or bank details are ever stored |
  | Subscriptions, purchases, enrollments | `billing_*`, `training_enrollment` | Low–medium |
  | Comments (with IP addresses for 90 days) | `django_comments_xtd_*`, `django_comments` | Low–medium |
  | Story pitches (contact details, drafts) | `pitches_storypitch` | Medium (may name sources) |
  | Newsletter list | `newsletter_subscriber` | Low |
  | Reader reports (reporter's contact details) | `admin_custom_contentreport` | Medium |
  | Sign-in attempts (email, IP, browser) | `axes_*` | Low |
  | Reading history and follows | `articles_*`, `sections_sectionfollow` | Low–medium; **health topics** can reveal health interests |

- **Whose data, and how many people.** Export the list of affected email addresses to a file (`affected.txt`, one per
  line). You'll need it for section 4.
- **The risk to those people:** could it lead to fraud, discrimination, embarrassment, or someone being identified as a
  source? Health-related interests and CVs count as higher risk.

## 3. Within 72 hours — tell the authorities (if required)

- **People in the EU or UK affected:** if the incident is likely to put them at risk, GDPR requires telling the relevant
  data-protection authority **within 72 hours** of finding out, even if the investigation isn't finished. Ask the lawyer
  which authority.
- **Nepal:** ask the lawyer what the Individual Privacy Act, 2075 and any other law in force require for this incident,
  and who must be told.
- **Payments involved:** tell Fonepay straight away.
- **A crime** (break-in, extortion): report it to the police (Nepal Police Cyber Bureau).

Record who you told, when, and what you said.

## 4. Without undue delay — tell the people affected

If the incident is likely to put people at risk, tell them directly, in plain language, and say:

1. what happened, and when;
2. which of their data was involved, and which wasn't (for example "no card or bank details — we never store them");
3. what you've done about it;
4. what they should do (for example change their password here and anywhere they reuse it, watch for phishing emails
   that look like ours);
5. who to contact with questions.

Write the message to a file (`notice.txt`; `{first_name}` is filled in per person). Check who it will go to, then send:

```bash
python manage.py notify_users --subject "Important: your Ajna Health Lens account" --message-file notice.txt --emails affected.txt
python manage.py notify_users --subject "Important: your Ajna Health Lens account" --message-file notice.txt --emails affected.txt --send
```

The first command is a dry run that lists the recipients; the second sends. Use `--all-active` instead of `--emails` if
everyone may be affected. If passwords may have leaked, also force resets: after changing `SECRET_KEY`, reset each
affected account's password from **Accounts** (an invite email lets them choose a new one).

## 5. Afterwards — learn from it

Within two weeks: what let it happen, what will stop it happening again, who does what by when. Fix the cause and update
this plan.

## 6. Incident log (copy for each incident)

```
Incident #:            Found by / at (date, time):
Lead:
Timeline:              (when it started, was found, was contained — with sources)
Data involved:
People affected:       (how many, which groups — file of emails kept at …)
Risk assessment:
Containment steps:     (what, who, when)
Authorities told:      (who, when, reference) — or why not required
People told:           (when, how, copy of the message) — or why not required
Root cause:
Follow-up actions:     (what, owner, due date, done?)
```

Keep logs for every incident, **including ones you decided didn't need reporting**, with the reason.

---

## Practice

Run through this plan once a year with a made-up incident, such as "a backup file was left in a public folder". Check
that the contacts are current and that someone other than the technical lead can do section 1.
