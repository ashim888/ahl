from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from articles.validators import article_image_extension_validator, validate_featured_image_size


def _lines(text: str) -> list[str]:
    """Non-blank, stripped lines of a one-item-per-line text field. Leading
    bullet characters an editor may have typed ("-", "*", "•") are dropped,
    since the template renders its own markers.
    """
    items = []
    for line in (text or '').splitlines():
        line = line.strip().lstrip('-*•').strip()
        if line:
            items.append(line)
    return items


HONORIFICS = {'dr', 'prof', 'mr', 'mrs', 'ms', 'miss', 'er'}


class TrainingCourse(models.Model):
    """A training program in the public catalog (/training/). The fields
    below `created_at` in the original scaffold were only title/description/
    price/duration/instructor/syllabus; the rest (September 2026) feed the
    course-catalog layout — outcomes, audience, level, format, schedule,
    instructor profile, modules (CourseModule) and FAQs.
    """

    class Level(models.TextChoices):
        BEGINNER = 'beginner', _('Beginner')
        INTERMEDIATE = 'intermediate', _('Intermediate')
        ADVANCED = 'advanced', _('Advanced')
        ALL_LEVELS = 'all_levels', _('All levels')

    class Mode(models.TextChoices):
        ONLINE = 'online', _('Online')
        IN_PERSON = 'in_person', _('In person')
        HYBRID = 'hybrid', _('Hybrid')

    title = models.CharField(max_length=255)
    subtitle = models.CharField(
        max_length=255, blank=True,
        help_text='One-line pitch shown under the title, e.g. "Go from research question to a publishable manuscript".',
    )
    category = models.CharField(
        max_length=100, blank=True,
        help_text='Topic used to group and filter courses, e.g. "Research Methods". Reuse the same spelling across courses.',
    )
    description = models.TextField(help_text='About this course — a few paragraphs.')
    cover_image = models.ImageField(
        upload_to='training/covers/', null=True, blank=True,
        validators=[article_image_extension_validator, validate_featured_image_size],
        help_text='Landscape image (about 1200×675). JPG or PNG.',
    )
    level = models.CharField(max_length=20, choices=Level.choices, default=Level.ALL_LEVELS)
    mode = models.CharField('Format', max_length=20, choices=Mode.choices, default=Mode.ONLINE)
    language = models.CharField(max_length=50, default='English')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration = models.CharField(max_length=50, help_text='e.g. "4 weeks"')
    effort = models.CharField(
        max_length=100, blank=True, help_text='Expected time commitment, e.g. "3–4 hours a week".',
    )
    start_date = models.DateField(null=True, blank=True, help_text='Leave empty if learners can start any time.')
    offers_certificate = models.BooleanField(
        default=False, help_text='Learners who complete the course receive a certificate.',
    )

    learning_outcomes = models.TextField(
        'What you\'ll learn', blank=True, help_text='One outcome per line. Shown as a checklist.',
    )
    audience = models.TextField(
        'Who this course is for', blank=True, help_text='One line per group, e.g. "Early-career researchers".',
    )
    prerequisites = models.TextField(blank=True, help_text='One per line. Leave empty if there are none.')
    faqs = models.TextField(
        'FAQs', blank=True,
        help_text='Separate each question with a blank line. First line of each block is the question, '
                  'the lines after it are the answer.',
    )

    instructor = models.CharField(max_length=255)
    instructor_title = models.CharField(
        max_length=255, blank=True, help_text='e.g. "Associate Professor of Epidemiology, Tribhuvan University".',
    )
    instructor_bio = models.TextField(blank=True)
    instructor_photo = models.ImageField(
        upload_to='training/instructors/', null=True, blank=True,
        validators=[article_image_extension_validator, validate_featured_image_size],
    )

    syllabus = models.TextField(
        null=True, blank=True,
        help_text='Free-text syllabus. Only shown when the course has no modules — prefer adding modules.',
    )
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(
        default=False, help_text='Highlight this course at the top of the training catalog.',
    )
    max_enrollments = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    @property
    def instructor_initial(self) -> str:
        """Avatar letter for the instructor — skips honorifics like "Dr."
        so "Dr. Sunita Rai" gets "S", not "D".
        """
        words = [w for w in self.instructor.split() if w.rstrip('.').lower() not in HONORIFICS]
        return (words[0][0] if words else self.instructor[:1]).upper()

    @property
    def learning_outcome_list(self) -> list[str]:
        return _lines(self.learning_outcomes)

    @property
    def audience_list(self) -> list[str]:
        return _lines(self.audience)

    @property
    def prerequisite_list(self) -> list[str]:
        return _lines(self.prerequisites)

    @property
    def faq_list(self) -> list[dict]:
        """`faqs` parsed into [{'question', 'answer'}] — blocks separated by
        a blank line, first line the question, the rest the answer. A block
        with no answer lines is skipped rather than shown as an empty entry.
        """
        entries = []
        for block in (self.faqs or '').replace('\r\n', '\n').split('\n\n'):
            lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
            if len(lines) >= 2:
                entries.append({'question': lines[0], 'answer': ' '.join(lines[1:])})
        return entries


class CourseModule(models.Model):
    """One unit of a course's syllabus ("Week 1 — Framing a research
    question"), shown as an expandable list on the course page.
    """

    course = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name='modules')
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True, help_text='What this module covers.')
    duration = models.CharField(max_length=50, blank=True, help_text='e.g. "Week 1" or "2 hours".')

    class Meta:
        ordering = ['order', 'pk']

    def __str__(self):
        return f'{self.course}: {self.title}'


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    class PaymentStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID = 'paid', 'Paid'
        REFUNDED = 'refunded', 'Refunded'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='enrollments',
    )
    course = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name='enrollments')
    enrolled_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING,
    )
    # TODO: Integrate Stripe — populated by billing.gateway once a real
    # processor is wired in; stub checkout (training/views.py) fills this
    # with a `stub-...` reference today (see billing/gateway.py).
    payment_reference = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ('user', 'course')

    def __str__(self):
        return f'{self.user} in {self.course}'
