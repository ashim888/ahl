import datetime

from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from articles.models import Article, ArticleAuthor
from issues.models import Issue
from peer_review.models import Review
from submissions.models import ManuscriptFile, Submission
from training.models import TrainingCourse
from users.models import User

# Model apps an Editor needs view/add/change access to in /admin/ — matches
# ARCHITECTURE.md §6.2 (Editor: assign reviewers, make decisions; not verify users).
EDITOR_PERMISSION_APPS = ['submissions', 'peer_review', 'articles', 'issues', 'training']

DEMO_PASSWORD = 'DemoPass123!'


def demo_pdf(name):
    return ContentFile(f'%PDF-1.4 demo content for {name}'.encode(), name=name)


class Command(BaseCommand):
    help = 'Seed realistic demo data (users, issues, articles, submissions, reviews, training courses) for local development.'

    def handle(self, *args, **options):
        with transaction.atomic():
            users = self.seed_users()
            issues = self.seed_issues()
            articles = self.seed_articles(users, issues)
            self.seed_submissions(users, articles)
            self.seed_training()

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

        # User verification is EiC/Admin-only (ARCHITECTURE.md §6.2) — granted
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
            dict(volume=1, number=1, title='Inaugural Issue', is_published=True,
                 publication_date=datetime.date(2026, 1, 15),
                 editorial_note='Welcome to the first issue of Ajna Health Lens.'),
            dict(volume=1, number=2, title='Maternal & Child Health', is_published=True,
                 publication_date=datetime.date(2026, 4, 1),
                 editorial_note='This issue focuses on maternal and child health outcomes across Nepal.'),
            dict(volume=2, number=1, title='In Production', is_published=False,
                 editorial_note='Not yet published — used to verify unpublished issues stay hidden.'),
        ]
        issues = {}
        for spec in specs:
            issue, _ = Issue.objects.get_or_create(volume=spec['volume'], number=spec['number'], defaults=spec)
            issues[(issue.volume, issue.number)] = issue
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
                 publication_date=datetime.date(2026, 1, 20), issue=issues[(1, 1)], volume='1', page_numbers='1-14',
                 doi='10.5555/ahl.2026.0001', authors=[(sharma, True), (thapa, False)]),
            dict(slug='systematic-review-tb-screening-methods',
                 title='A Systematic Review of Community-Based Tuberculosis Screening Methods',
                 abstract='We systematically review community-based TB screening approaches used across '
                          'South Asia, comparing sensitivity, cost, and scalability.',
                 keywords='tuberculosis, screening, systematic review, South Asia',
                 article_type=Article.ArticleType.REVIEW_ARTICLE, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 1, 25), issue=issues[(1, 1)], volume='1', page_numbers='15-32',
                 doi='10.5555/ahl.2026.0002', authors=[(thapa, True)]),
            dict(slug='letter-response-antenatal-care-study',
                 title='Letter: A Response to the Antenatal Care Access Study',
                 abstract='A brief response raising methodological questions about sampling in the antenatal '
                          'care access literature.',
                 keywords='letter, antenatal care, methodology',
                 article_type=Article.ArticleType.LETTER_TO_EDITOR, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 2, 1), issue=issues[(1, 1)], volume='1', page_numbers='33-34',
                 authors=[(karki, True)]),
            dict(slug='case-report-rare-cardiac-presentation',
                 title='A Rare Cardiac Presentation in a Young Adult: A Case Report',
                 abstract='We report a rare cardiac presentation in a 24-year-old patient, detailing diagnostic '
                          'workup and management.',
                 keywords='case report, cardiology, young adult',
                 article_type=Article.ArticleType.CASE_REPORT, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 4, 5), issue=issues[(1, 2)], volume='1', page_numbers='1-6',
                 authors=[(karki, True)]),
            dict(slug='short-communication-child-nutrition-pilot',
                 title='Short Communication: Preliminary Findings from a Child Nutrition Pilot Program',
                 abstract='Preliminary data from a six-month child nutrition pilot program in three rural districts.',
                 keywords='child nutrition, pilot program, preliminary findings',
                 article_type=Article.ArticleType.SHORT_COMMUNICATION, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 4, 10), issue=issues[(1, 2)], volume='1', page_numbers='7-10',
                 authors=[(sharma, True)]),
            dict(slug='editorial-strengthening-rural-health-systems',
                 title='Editorial: Strengthening Rural Health Systems Through Local Research',
                 abstract='An editorial on why locally-led research is essential to strengthening rural health '
                          'systems in Nepal.',
                 keywords='editorial, health systems, rural health',
                 article_type=Article.ArticleType.EDITORIAL, status=Article.Status.PUBLISHED,
                 publication_date=datetime.date(2026, 5, 1), authors=[(users['eic@ajnahealthlens.example'], True)]),
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
            article, created = Article.objects.get_or_create(slug=spec['slug'], defaults=spec)
            if created:
                for order, (author, is_corresponding) in enumerate(authors):
                    ArticleAuthor.objects.get_or_create(
                        article=article, user=author,
                        defaults=dict(order=order, is_corresponding=is_corresponding),
                    )
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
