import datetime

from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from ads.models import AdSlot
from articles.models import Article, ArticleAuthor, ArticleView
from billing.models import PlanFeature, SubscriptionPlan
from editorial_board.models import EditorialBoardMember
from issues.models import Issue
from peer_review.models import Review
from submissions.models import ManuscriptFile, Submission
from training.models import TrainingCourse
from users.models import User

# Model apps an Editor needs view/add/change access to in /admin/ — matches
# ARCHITECTURE.md §6.3 (Editor: assign reviewers, make decisions; not verify users).
EDITOR_PERMISSION_APPS = ['submissions', 'peer_review', 'articles', 'issues', 'training']

DEMO_PASSWORD = 'DemoPass123!'


def demo_pdf(name):
    return ContentFile(f'%PDF-1.4 demo content for {name}'.encode(), name=name)


def demo_jpeg(name, size=(600, 200), color=(210, 210, 200)):
    """A real, validly-encoded JPEG (via Pillow, already a project
    dependency) — not just renamed text bytes, since it needs to actually
    render as an <img> in the demo (ad banners, etc.), not just pass an
    extension check.
    """
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new('RGB', size, color=color).save(buffer, format='JPEG')
    return ContentFile(buffer.getvalue(), name=name)


# Full-text body for the case report demo article — shows what an open-access
# article's html_content looks like once populated, including an inline D3.js
# chart and [N] citation placeholders. These are plain text as an editor
# would type them in CKEditor — articles/citations.linkify_citations() turns
# them into hyperlinked superscripts pointing at the References section at
# render time (see templates/articles/article_detail.html's #ref-N anchors).
CASE_REPORT_HTML_CONTENT = """
<h2>Introduction</h2>
<p>Acute myocarditis in young, otherwise healthy adults is an uncommon but clinically significant
cause of chest pain and troponin elevation, frequently mimicking acute coronary syndrome on initial
presentation.[1] Distinguishing myocarditis from an acute coronary event
early is essential, since management and short-term risk differ substantially.[2]
We describe a young adult presenting with pleuritic chest pain and a markedly elevated troponin trend
following a recent viral illness.</p>

<h2>Case Presentation</h2>
<p>A 24-year-old previously healthy man presented to the emergency department with two days of
pleuritic chest pain, low-grade fever, and fatigue, one week after a self-limited upper respiratory
illness. Electrocardiography showed diffuse concave ST-segment elevation without reciprocal changes.
Initial high-sensitivity troponin I was mildly elevated at 0.8 ng/mL. Coronary risk factors were
absent and the patient was hemodynamically stable throughout admission.</p>

<h2>Investigations</h2>
<p>Serial troponin I measurements over the following 72 hours showed a rise-and-fall pattern more
consistent with myocarditis than an evolving coronary occlusion, corroborated by cardiac MRI findings
of subepicardial late gadolinium enhancement in the inferolateral wall — a pattern well described in
viral myocarditis.[3]</p>

<figure>
  <div id="troponin-chart" style="max-width: 640px;"></div>
  <figcaption>Figure 1. Serial high-sensitivity troponin I (ng/mL) over the first 72 hours of admission.</figcaption>
</figure>
<script>
(function () {
  var data = [
    { hour: 0, troponin: 0.8 },
    { hour: 12, troponin: 4.2 },
    { hour: 24, troponin: 6.1 },
    { hour: 48, troponin: 3.5 },
    { hour: 72, troponin: 1.1 }
  ];
  var margin = { top: 20, right: 30, bottom: 45, left: 55 },
      width = 640 - margin.left - margin.right,
      height = 320 - margin.top - margin.bottom;

  var svg = d3.select('#troponin-chart')
    .append('svg')
      .attr('viewBox', '0 0 ' + (width + margin.left + margin.right) + ' ' + (height + margin.top + margin.bottom))
      .attr('width', '100%')
    .append('g')
      .attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

  var x = d3.scaleLinear().domain([0, 72]).range([0, width]);
  var y = d3.scaleLinear().domain([0, 7]).range([height, 0]);

  svg.append('g')
    .attr('transform', 'translate(0,' + height + ')')
    .call(d3.axisBottom(x).tickValues([0, 12, 24, 48, 72]));
  svg.append('g').call(d3.axisLeft(y));

  var line = d3.line().x(function (d) { return x(d.hour); }).y(function (d) { return y(d.troponin); });

  svg.append('path')
    .datum(data)
    .attr('fill', 'none')
    .attr('stroke', '#111827')
    .attr('stroke-width', 2)
    .attr('d', line);

  svg.selectAll('circle')
    .data(data)
    .enter()
    .append('circle')
      .attr('cx', function (d) { return x(d.hour); })
      .attr('cy', function (d) { return y(d.troponin); })
      .attr('r', 4)
      .attr('fill', '#111827');

  svg.append('text')
    .attr('x', width / 2).attr('y', height + 38)
    .attr('text-anchor', 'middle').style('font-size', '12px').style('fill', '#4b5563')
    .text('Hours since presentation');

  svg.append('text')
    .attr('transform', 'rotate(-90)')
    .attr('x', -height / 2).attr('y', -40)
    .attr('text-anchor', 'middle').style('font-size', '12px').style('fill', '#4b5563')
    .text('Troponin I (ng/mL)');
})();
</script>

<h2>Discussion</h2>
<p>The differential for young patients presenting with chest pain and troponin elevation includes
acute coronary syndrome, pericarditis, and myocarditis.[4] A preceding
viral prodrome, diffuse (rather than territorial) ECG changes, and a troponin trajectory that peaks
and resolves within days — rather than the more sustained elevation typical of infarction — favor
myocarditis, as does subepicardial (rather than subendocardial) late gadolinium enhancement on
MRI.[5] Most cases in young, hemodynamically stable patients are
self-limited and managed conservatively, though structured follow-up is warranted given a small
but recognized risk of late ventricular dysfunction.[6][7]</p>

<h2>Conclusion</h2>
<p>Myocarditis should remain a key differential in young adults presenting with chest pain and
troponin elevation following a viral illness. Serial troponin trends and cardiac MRI are valuable
in distinguishing it from acute coronary syndrome and guiding a conservative management
approach.[8]</p>
""".strip()

CASE_REPORT_REFERENCES = """
Caforio ALP, Pankuweit S, Arbustini E, et al. Current state of knowledge on aetiology, diagnosis, management, and therapy of myocarditis: a position statement of the European Society of Cardiology Working Group on Myocardial and Pericardial Diseases. Eur Heart J. 2013;34(33):2636-2648.
Kociol RD, Cooper LT, Fang JC, et al. Recognition and initial management of fulminant myocarditis: a scientific statement from the American Heart Association. Circulation. 2020;141(6):e69-e92.
Ferreira VM, Schulz-Menger J, Holmvang G, et al. Cardiovascular magnetic resonance in nonischemic myocardial inflammation: expert recommendations. J Am Coll Cardiol. 2018;72(24):3158-3176.
Sharma A, Gurung R. Distinguishing acute coronary syndrome from myocarditis in young adults: a diagnostic approach. J Cardiol Nepal. 2024;12(3):145-152.
Luetkens JA, Faron A, Isaak A, et al. Comparison of original and 2018 Lake Louise criteria for diagnosis of acute myocarditis. Radiol Cardiothorac Imaging. 2019;1(3):e190010.
Ammirati E, Frigerio M, Adler ED, et al. Management of acute myocarditis and chronic inflammatory cardiomyopathy: an expert consensus document. Circ Heart Fail. 2020;13(11):e007405.
Anzini M, Merlo M, Sabbadini G, et al. Long-term evolution and prognostic stratification of biopsy-proven active myocarditis. Circulation. 2013;128(22):2384-2394.
Thapa B, Karki S. A case series of viral myocarditis mimicking acute coronary syndrome in a tertiary centre in Nepal. Ajna Health Lens. 2025;1(3):22-29. https://doi.org/10.1234/ahl.2025.010329
""".strip()


class Command(BaseCommand):
    help = ('Seed realistic demo data (users, issues, articles, submissions, reviews, training courses, '
            'subscription plans) for local development.')

    def handle(self, *args, **options):
        with transaction.atomic():
            users = self.seed_users()
            issues = self.seed_issues()
            articles = self.seed_articles(users, issues)
            self.seed_submissions(users, articles)
            self.seed_training()
            self.seed_editorial_board()
            self.seed_subscription_plans()
            self.seed_ads()
            self.seed_article_views(articles)

        self.stdout.write(self.style.SUCCESS('\nDemo data seeded.'))
        self.stdout.write(f'All seeded users share the password: {DEMO_PASSWORD}')
        self.stdout.write('Admin login: admin@ajnahealthlens.example')

    # -- Users ---------------------------------------------------------

    def seed_users(self):
        self.stdout.write('Seeding users...')
        specs = [
            dict(email='admin@ajnahealthlens.example', first_name='Site', last_name='Admin',
                 role=User.Role.ADMIN, is_staff=True, is_superuser=True,
                 is_verified=True, verification_status=User.VerificationStatus.APPROVED),
            dict(email='eic@ajnahealthlens.example', first_name='Sunita', last_name='Rai',
                 role=User.Role.EDITOR_IN_CHIEF, is_staff=True,
                 is_verified=True, verification_status=User.VerificationStatus.APPROVED,
                 affiliation='Ajna Health Lens', department='Editorial Office'),
            dict(email='editor.gurung@ajnahealthlens.example', first_name='Rajesh', last_name='Gurung',
                 role=User.Role.EDITOR, is_staff=True,
                 is_verified=True, verification_status=User.VerificationStatus.APPROVED,
                 affiliation='B.P. Koirala Institute of Health Sciences'),
            dict(email='reviewer.koirala@example.com', first_name='Priya', last_name='Koirala',
                 role=User.Role.REVIEWER,
                 is_verified=True, verification_status=User.VerificationStatus.APPROVED,
                 affiliation='Kathmandu University', orcid='0000-0001-2345-6789',
                 research_interests='Epidemiology, public health policy'),
            dict(email='reviewer.basnet@example.com', first_name='Kiran', last_name='Basnet',
                 role=User.Role.REVIEWER,
                 is_verified=True, verification_status=User.VerificationStatus.APPROVED,
                 affiliation='Patan Academy of Health Sciences'),
            dict(email='author.sharma@example.com', first_name='Anjali', last_name='Sharma',
                 role=User.Role.VERIFIED_AUTHOR,
                 is_verified=True, verification_status=User.VerificationStatus.APPROVED,
                 affiliation='Tribhuvan University', department='Community Medicine',
                 orcid='0000-0002-1825-0097', research_interests='Maternal health, rural healthcare access',
                 linkedin_url='https://linkedin.com/in/anjali-sharma-demo'),
            dict(email='author.thapa@example.com', first_name='Bikash', last_name='Thapa',
                 role=User.Role.VERIFIED_AUTHOR,
                 is_verified=True, verification_status=User.VerificationStatus.APPROVED,
                 affiliation='Patan Academy of Health Sciences', department='Internal Medicine',
                 research_interests='Infectious disease, tuberculosis screening'),
            dict(email='author.karki@example.com', first_name='Suresh', last_name='Karki',
                 role=User.Role.VERIFIED_AUTHOR,
                 is_verified=True, verification_status=User.VerificationStatus.APPROVED,
                 affiliation='Kathmandu Medical College',
                 research_interests='Cardiology'),
            dict(email='pending.adhikari@example.com', first_name='Meena', last_name='Adhikari',
                 role=User.Role.UNVERIFIED, verification_status=User.VerificationStatus.PENDING,
                 affiliation='Nepal Health Research Council',
                 publications='First-time submitter, no prior publications listed.'),
            dict(email='rejected.thapa@example.com', first_name='Gita', last_name='Magar',
                 role=User.Role.UNVERIFIED, verification_status=User.VerificationStatus.REJECTED,
                 verification_status_changed_at=timezone.now() - datetime.timedelta(days=5)),
        ]

        users = {}
        for spec in specs:
            email = spec.pop('email')
            user, created = User.objects.get_or_create(email=email, defaults=spec)
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            users[email] = user
        self.stdout.write(f'  {len(users)} users ready.')

        # is_staff alone only unlocks the /admin/ login — Django still checks
        # per-model permissions for each changelist, so editorial staff need an
        # actual permission grant or their seeded accounts can't do anything there.
        editors_group, _ = Group.objects.get_or_create(name='Editorial Staff')
        editors_group.permissions.set(Permission.objects.filter(
            content_type__app_label__in=EDITOR_PERMISSION_APPS,
            codename__regex=r'^(view|add|change)_',
        ))
        for email in ('eic@ajnahealthlens.example', 'editor.gurung@ajnahealthlens.example'):
            users[email].groups.add(editors_group)

        # User verification is EiC/Admin-only (ARCHITECTURE.md §6.3) — granted
        # directly to the EiC, not via the shared Editorial Staff group, so
        # Editor accounts don't pick it up too.
        eic = users['eic@ajnahealthlens.example']
        eic.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='users', codename__in=['view_user', 'change_user'],
        ))

        return users

    # -- Issues ----------------------------------------------------------

    def seed_issues(self):
        self.stdout.write('Seeding issues...')
        specs = [
            dict(slug='inaugural-issue', title='Inaugural Issue', is_published=True,
                 publication_date=datetime.date(2026, 1, 15),
                 editorial_note='Welcome to the first issue of Ajna Health Lens.'),
            dict(slug='maternal-child-health', title='Maternal & Child Health', is_published=True,
                 publication_date=datetime.date(2026, 4, 1),
                 editorial_note='This issue focuses on maternal and child health outcomes across Nepal.'),
            dict(slug='in-production', title='In Production', is_published=False,
                 editorial_note='Not yet published — used to verify unpublished issues stay hidden.'),
        ]
        issues = {}
        for spec in specs:
            issue, _ = Issue.objects.get_or_create(slug=spec['slug'], defaults=spec)
            issues[issue.slug] = issue
        self.stdout.write(f'  {len(issues)} issues ready.')
        return issues

    # -- Articles ----------------------------------------------------------

    def seed_articles(self, users, issues):
        self.stdout.write('Seeding articles...')
        sharma, thapa, karki = users['author.sharma@example.com'], users['author.thapa@example.com'], users['author.karki@example.com']

        specs = [
            dict(slug='maternal-health-outcomes-rural-nepal',
                 title='Maternal Health Outcomes in Rural Nepal: A Retrospective Cohort Study',
                 abstract='This retrospective cohort study examines maternal health outcomes across rural '
                          'health posts in Nepal between 2020 and 2025, identifying key gaps in antenatal care access.',
                 keywords='maternal health, Nepal, rural healthcare, antenatal care',
                 article_type=Article.ArticleType.ORIGINAL_RESEARCH, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 1, 20), issue=issues['inaugural-issue'], volume='1', page_numbers='1-14',
                 doi='10.5555/ahl.2026.0001', authors=[(sharma, True), (thapa, False)],
                 # Editorially chosen as the lead story even though it isn't the
                 # most recently published article — demonstrates that
                 # homepage_section overrides the "most recent" hero default.
                 homepage_section=Article.HomepageSection.HERO),
            dict(slug='systematic-review-tb-screening-methods',
                 title='A Systematic Review of Community-Based Tuberculosis Screening Methods',
                 abstract='We systematically review community-based TB screening approaches used across '
                          'South Asia, comparing sensitivity, cost, and scalability.',
                 keywords='tuberculosis, screening, systematic review, South Asia',
                 article_type=Article.ArticleType.REVIEW_ARTICLE, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 1, 25), issue=issues['inaugural-issue'], volume='1', page_numbers='15-32',
                 doi='10.5555/ahl.2026.0002', authors=[(thapa, True)],
                 homepage_section=Article.HomepageSection.RESEARCH),
            dict(slug='letter-response-antenatal-care-study',
                 title='Letter: A Response to the Antenatal Care Access Study',
                 abstract='A brief response raising methodological questions about sampling in the antenatal '
                          'care access literature.',
                 keywords='letter, antenatal care, methodology',
                 article_type=Article.ArticleType.LETTER_TO_EDITOR, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 2, 1), issue=issues['inaugural-issue'], volume='1', page_numbers='33-34',
                 authors=[(karki, True)]),
            dict(slug='case-report-rare-cardiac-presentation',
                 title='A Rare Cardiac Presentation in a Young Adult: A Case Report',
                 abstract='We report a rare cardiac presentation in a 24-year-old patient, detailing diagnostic '
                          'workup and management.',
                 keywords='case report, cardiology, young adult',
                 article_type=Article.ArticleType.CASE_REPORT, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 4, 5), issue=issues['maternal-child-health'], volume='1', page_numbers='1-6',
                 html_content=CASE_REPORT_HTML_CONTENT, references=CASE_REPORT_REFERENCES,
                 authors=[(karki, True)], homepage_section=Article.HomepageSection.RESEARCH),
            dict(slug='short-communication-child-nutrition-pilot',
                 title='Short Communication: Preliminary Findings from a Child Nutrition Pilot Program',
                 abstract='Preliminary data from a six-month child nutrition pilot program in three rural districts.',
                 keywords='child nutrition, pilot program, preliminary findings',
                 article_type=Article.ArticleType.SHORT_COMMUNICATION, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 4, 10), issue=issues['maternal-child-health'], volume='1', page_numbers='7-10',
                 authors=[(sharma, True)]),
            dict(slug='editorial-strengthening-rural-health-systems',
                 title='Editorial: Strengthening Rural Health Systems Through Local Research',
                 abstract='An editorial on why locally-led research is essential to strengthening rural health '
                          'systems in Nepal.',
                 keywords='editorial, health systems, rural health',
                 article_type=Article.ArticleType.EDITORIAL, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 5, 1), authors=[(users['eic@ajnahealthlens.example'], True)],
                 homepage_section=Article.HomepageSection.OPINION),
            dict(slug='news-tb-screening-guidelines-update',
                 title='Nepal Issues New Tuberculosis Screening Guidelines',
                 abstract='The Ministry of Health has released updated TB screening guidelines for community '
                          'health workers, effective this quarter.',
                 keywords='tuberculosis, screening, policy, news',
                 article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 2, 10), authors=[]),
            dict(slug='news-health-ministry-budget-announcement',
                 title='Health Ministry Announces Increased Budget for Rural Clinics',
                 abstract='A policy brief on the newly announced budget allocation for rural clinic infrastructure.',
                 keywords='policy, budget, rural clinics, news',
                 article_type=Article.ArticleType.NEWS_COMMENTARY, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 3, 15), authors=[]),
            dict(slug='methodology-mixed-methods-framework-draft',
                 title='A Mixed-Methods Framework for Community Health Research (Draft)',
                 abstract='A proposed mixed-methods framework, currently in editorial draft review.',
                 keywords='methodology, mixed methods, community health',
                 article_type=Article.ArticleType.METHODOLOGY_PAPER, status=Article.Status.DRAFT,
                 authors=[(thapa, True)]),
        ]

        articles = {}
        for spec in specs:
            authors = spec.pop('authors')
            homepage_section = spec.pop('homepage_section', '')
            article, created = Article.objects.get_or_create(slug=spec['slug'], defaults=spec)
            if created:
                for order, (author, is_corresponding) in enumerate(authors):
                    ArticleAuthor.objects.get_or_create(
                        article=article, user=author,
                        defaults=dict(order=order, is_corresponding=is_corresponding),
                    )
            # Re-applied even on an already-seeded DB (unlike the rest of
            # `spec`, which only takes on a fresh create) — homepage curation
            # is the whole point of this seed step, so a re-run should always
            # leave the homepage looking right rather than silently no-op'ing
            # on rows created before this field existed.
            if article.homepage_section != homepage_section:
                article.homepage_section = homepage_section
                article.save(update_fields=['homepage_section'])
            articles[article.slug] = article
        self.stdout.write(f'  {len(articles)} articles ready.')
        return articles

    # -- Submissions & reviews ------------------------------------------

    def seed_submissions(self, users, articles):
        self.stdout.write('Seeding submissions...')
        sharma, thapa, karki = users['author.sharma@example.com'], users['author.thapa@example.com'], users['author.karki@example.com']
        gurung = users['editor.gurung@ajnahealthlens.example']
        koirala, basnet = users['reviewer.koirala@example.com'], users['reviewer.basnet@example.com']

        specs = [
            dict(title='Antibiotic Resistance Patterns in Urban Nepal',
                 article_type=Article.ArticleType.ORIGINAL_RESEARCH,
                 abstract='A cross-sectional study of antibiotic resistance patterns across three urban hospitals.',
                 submitter=karki, status=Submission.Status.SUBMITTED),
            dict(title='Vaccine Hesitancy Among Rural Caregivers',
                 article_type=Article.ArticleType.ORIGINAL_RESEARCH,
                 abstract='A qualitative study exploring the drivers of vaccine hesitancy among rural caregivers.',
                 submitter=sharma, status=Submission.Status.UNDER_SCREENING, editor_assigned=gurung,
                 screening_notes='Scope and format check in progress.'),
            dict(title='Telemedicine Adoption in Remote Districts',
                 article_type=Article.ArticleType.ORIGINAL_RESEARCH,
                 abstract='An evaluation of telemedicine adoption rates across five remote districts post-rollout.',
                 submitter=thapa, status=Submission.Status.UNDER_REVIEW, editor_assigned=gurung,
                 screening_notes='Passed screening, sent to review.',
                 reviews=[(koirala, Review.Status.ACCEPTED), (basnet, Review.Status.INVITED)]),
            dict(title='Dietary Patterns and Anemia in Adolescent Girls',
                 article_type=Article.ArticleType.ORIGINAL_RESEARCH,
                 abstract='A survey-based study of dietary patterns and anemia prevalence among adolescent girls.',
                 submitter=sharma, status=Submission.Status.MINOR_REVISION, editor_assigned=gurung,
                 revision_round=1, decision='minor_revision', decision_date=timezone.now() - datetime.timedelta(days=3)),
            dict(title='Surgical Site Infection Rates: A Multi-Center Study',
                 article_type=Article.ArticleType.ORIGINAL_RESEARCH,
                 abstract='A multi-center study of surgical site infection rates and contributing risk factors.',
                 submitter=karki, status=Submission.Status.MAJOR_REVISION, editor_assigned=gurung,
                 revision_round=1, decision='major_revision', decision_date=timezone.now() - datetime.timedelta(days=10)),
            dict(title='Community Health Worker Retention Strategies',
                 article_type=Article.ArticleType.ORIGINAL_RESEARCH,
                 abstract='An analysis of retention strategies for community health workers in hill districts.',
                 submitter=thapa, status=Submission.Status.ACCEPTED, editor_assigned=gurung,
                 decision='accept', decision_date=timezone.now() - datetime.timedelta(days=2)),
            dict(title='A Flawed Study of Herbal Remedies for Hypertension',
                 article_type=Article.ArticleType.ORIGINAL_RESEARCH,
                 abstract='A study of herbal remedies for hypertension management with significant methodological concerns.',
                 submitter=karki, status=Submission.Status.REJECTED, editor_assigned=gurung,
                 decision='reject', decision_date=timezone.now() - datetime.timedelta(days=7),
                 screening_notes='Rejected after review: insufficient sample size, no control group.'),
            dict(title='Air Pollution Exposure and Pediatric Asthma in Kathmandu Valley',
                 article_type=Article.ArticleType.ORIGINAL_RESEARCH,
                 abstract='A cohort study linking air pollution exposure to pediatric asthma incidence in Kathmandu Valley.',
                 submitter=sharma, status=Submission.Status.IN_PRODUCTION, editor_assigned=gurung,
                 decision='accept', decision_date=timezone.now() - datetime.timedelta(days=14)),
            dict(title='Maternal Health Outcomes in Rural Nepal: A Retrospective Cohort Study',
                 article_type=Article.ArticleType.ORIGINAL_RESEARCH,
                 abstract='This retrospective cohort study examines maternal health outcomes across rural '
                          'health posts in Nepal between 2020 and 2025, identifying key gaps in antenatal care access.',
                 submitter=sharma, status=Submission.Status.PUBLISHED, editor_assigned=gurung,
                 decision='accept', decision_date=timezone.now() - datetime.timedelta(days=30),
                 promote_to='maternal-health-outcomes-rural-nepal'),
        ]

        count = 0
        for spec in specs:
            reviews = spec.pop('reviews', [])
            promote_to = spec.pop('promote_to', None)
            submission, created = Submission.objects.get_or_create(
                title=spec['title'], submitter=spec['submitter'], defaults=spec,
            )
            if created:
                count += 1
                filename = f'{submission.pk}_manuscript_v1.pdf'
                ManuscriptFile.objects.create(
                    submission=submission, file_type=ManuscriptFile.FileType.PDF, version=1,
                    file=demo_pdf(filename),
                )
                for reviewer, status in reviews:
                    Review.objects.get_or_create(
                        submission=submission, reviewer=reviewer,
                        defaults=dict(status=status, due_date=datetime.date.today() + datetime.timedelta(days=21)),
                    )
                if promote_to:
                    article = Article.objects.filter(slug=promote_to).first()
                    if article and not article.submission_id:
                        article.submission = submission
                        article.save(update_fields=['submission'])

        self.stdout.write(f'  {count} submissions created.')

    # -- Training ------------------------------------------------------

    def seed_training(self):
        self.stdout.write('Seeding training courses...')
        specs = [
            dict(title='Research Writing Fundamentals',
                 description='A foundational course on structuring and writing a publishable research manuscript.',
                 price=49.00, duration='4 weeks', instructor='Dr. Sunita Rai',
                 syllabus='Week 1: Structure. Week 2: Abstracts. Week 3: Methods & Results. Week 4: Peer review.'),
            dict(title='Research Methodology Bootcamp',
                 description='An intensive bootcamp covering study design, sampling, and statistical analysis basics.',
                 price=99.00, duration='6 weeks', instructor='Dr. Rajesh Gurung'),
            dict(title='Research Visibility Workshop',
                 description='Learn how to promote and disseminate your published work effectively.',
                 price=29.00, duration='2 weeks', instructor='Dr. Priya Koirala'),
        ]
        count = 0
        for spec in specs:
            _, created = TrainingCourse.objects.get_or_create(title=spec['title'], defaults=spec)
            count += created
        self.stdout.write(f'  {count} training courses created.')

    # -- Editorial board -------------------------------------------------

    def seed_editorial_board(self):
        self.stdout.write('Seeding editorial board...')
        specs = [
            dict(name='Dr. Sunita Rai', role_title='Editor-in-Chief',
                 affiliation='Ajna Health Lens', order=0,
                 bio='Sunita Rai leads the editorial team with a focus on rural health equity and '
                     'evidence-based public health policy across Nepal.'),
            dict(name='Dr. Rajesh Gurung', role_title='Editor',
                 affiliation='B.P. Koirala Institute of Health Sciences', order=1,
                 bio='Rajesh Gurung oversees manuscript screening and editorial decisions, with a '
                     'research background in infectious disease epidemiology.'),
            dict(name='Dr. Priya Koirala', role_title='Associate Editor, Public Health',
                 affiliation='Kathmandu University', order=2,
                 bio='Priya Koirala specializes in epidemiology and public health policy, and advises '
                     'on the journal\'s research methodology standards.'),
            dict(name='Dr. Kiran Basnet', role_title='Associate Editor, Clinical Medicine',
                 affiliation='Patan Academy of Health Sciences', order=3,
                 bio='Kiran Basnet brings clinical research experience in internal medicine to the '
                     'editorial board\'s review of case reports and clinical studies.'),
        ]
        count = 0
        for spec in specs:
            _, created = EditorialBoardMember.objects.get_or_create(name=spec['name'], defaults=spec)
            count += created
        self.stdout.write(f'  {count} editorial board members created.')

    # -- Subscription plans -----------------------------------------------

    def seed_subscription_plans(self):
        self.stdout.write('Seeding subscription plans...')

        # Ordered master feature list — every plan opts into a prefix of this
        # list, so higher tiers strictly include everything lower tiers get,
        # plus more (the standard SaaS pricing-table shape).
        feature_labels = [
            'Full access to subscriber-only articles',
            'Free access to special (pay-per-article) content',
            'Ad-free reading',
            'Weekly newsletter digest',
            'Downloadable PDF archive',
            'Priority customer support',
            'Early access to new platform features',
            'Multi-user access (up to 50 reader seats)',
            'Organization-wide IP-based access',
            'Usage analytics dashboard for admins',
            'Dedicated account manager',
            'Custom invoicing',
        ]
        features = {}
        for order, label in enumerate(feature_labels):
            feature, _ = PlanFeature.objects.get_or_create(label=label, defaults={'order': order})
            features[label] = feature

        specs = [
            dict(name='Reader Monthly', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_MONTHLY,
                 price=499, duration_days=30,
                 description='Full digital access to Ajna Health Lens, billed monthly. Cancel anytime.',
                 feature_count=4),
            dict(name='Reader Annual', plan_type=SubscriptionPlan.PlanType.INDIVIDUAL_ANNUAL,
                 price=4999, duration_days=365, is_featured=True,
                 description='Our best value for individual readers — pay for 10 months, read for 12, '
                              'plus priority support and early access to new features.',
                 feature_count=7),
            dict(name='Institutional', plan_type=SubscriptionPlan.PlanType.INSTITUTIONAL,
                 price=49999, duration_days=365,
                 description='Campus- or organization-wide access for universities, hospitals, and '
                              'research institutions, with usage reporting and a dedicated account manager.',
                 feature_count=len(feature_labels)),
        ]

        count = 0
        for spec in specs:
            feature_count = spec.pop('feature_count')
            plan, created = SubscriptionPlan.objects.get_or_create(name=spec['name'], defaults=spec)
            if created:
                count += 1
            plan.features.set([features[label] for label in feature_labels[:feature_count]])

        self.stdout.write(f'  {count} subscription plans created.')

    # -- Ads --------------------------------------------------------------

    def seed_ads(self):
        self.stdout.write('Seeding ads...')
        # One sponsor per zone, image generated at that zone's exact
        # required size (AdSlot.ZONE_DIMENSIONS) — demonstrates the fixed-
        # size system end to end, not just seeding data that happens to
        # bypass AdSlotForm's dimension validation (management commands
        # write via the ORM directly, not the form).
        specs = [
            dict(sponsor_name='Himalayan Diagnostics Lab', zone=AdSlot.Zone.HEADER_LEADERBOARD,
                 link_url='https://example.com/himalayan-diagnostics'),
            dict(sponsor_name="St. Xavier's Pharmacy", zone=AdSlot.Zone.MOBILE_ANCHOR,
                 link_url='https://example.com/st-xaviers-pharmacy'),
            dict(sponsor_name='Everest Wellness App', zone=AdSlot.Zone.MOBILE_LARGE_BANNER,
                 link_url='https://example.com/everest-wellness'),
            dict(sponsor_name='Patan Eye Care Center', zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1,
                 link_url='https://example.com/patan-eye-care'),
            dict(sponsor_name='Kathmandu Physiotherapy Clinic', zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_2,
                 link_url='https://example.com/kathmandu-physio'),
            dict(sponsor_name='Annapurna Dental Care', zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_3,
                 link_url='https://example.com/annapurna-dental'),
            dict(sponsor_name='Norvic International Hospital', zone=AdSlot.Zone.HOMEPAGE_LEADERBOARD,
                 link_url='https://example.com/norvic-hospital'),
            dict(sponsor_name='Kathmandu Medical Conference 2026', zone=AdSlot.Zone.ARTICLE_IN_CONTENT,
                 link_url='https://example.com/kmc-2026'),
            dict(sponsor_name='Bir Hospital Diagnostics', zone=AdSlot.Zone.ARTICLE_SIDEBAR,
                 link_url='https://example.com/bir-hospital-diagnostics'),
            dict(sponsor_name='Nepal Public Health Fellowship', zone=AdSlot.Zone.ARTICLE_SIDEBAR_HALF_PAGE,
                 link_url='https://example.com/nph-fellowship'),
        ]
        count = 0
        for spec in specs:
            ad, created = AdSlot.objects.get_or_create(
                sponsor_name=spec['sponsor_name'], defaults={
                    **spec, 'image': demo_jpeg(f"{spec['zone']}.jpg", size=AdSlot.ZONE_DIMENSIONS[spec['zone']]),
                },
            )
            count += created
        self.stdout.write(f'  {count} ads created.')

    # -- Article page views (for the homepage's Trending section) ---------

    def seed_article_views(self, articles):
        self.stdout.write('Seeding article page views...')
        # A handful of published articles get simulated recent traffic so
        # the homepage's Trending This Week section (purely data-driven,
        # not editor-curated — see HomeView) has something to show out of
        # the box instead of sitting empty until real readers show up.
        trending_slugs = [
            'maternal-health-outcomes-rural-nepal',
            'news-tb-screening-guidelines-update',
            'case-report-rare-cardiac-presentation',
        ]
        view_counts = [12, 8, 5]
        count = 0
        for slug, views in zip(trending_slugs, view_counts):
            article = articles.get(slug)
            if not article:
                continue
            existing = ArticleView.objects.filter(article=article).count()
            for i in range(max(views - existing, 0)):
                # session_key is max_length=40 — a short synthetic key,
                # unique per (article, i), is enough to avoid the live
                # dedup window ever colliding across these seeded rows.
                ArticleView.objects.create(article=article, session_key=f'seed-{article.pk}-{i}')
                count += 1
        self.stdout.write(f'  {count} article views created.')
