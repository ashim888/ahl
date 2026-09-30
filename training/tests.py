from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from billing.gateway import PaymentResult
from users.models import User

from .models import Enrollment, TrainingCourse

# See ARCHITECTURE.md §9.4 / users/tests.py:FAST_PASSWORD_HASHERS — a burst
# of create_user() calls with real PBKDF2 hashing is slow enough to matter
# once a test creates more than a handful of users (here, 35 enrollees).
FAST_PASSWORD_HASHERS = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


class CourseManageListFilterTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='course-filter-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.client.force_login(self.editor)

    def test_filters_by_active_status(self):
        active_course = TrainingCourse.objects.create(
            title='Active Course', description='...', price=10, duration='2 weeks',
            instructor='Dr. A', is_active=True,
        )
        TrainingCourse.objects.create(
            title='Inactive Course', description='...', price=10, duration='2 weeks',
            instructor='Dr. B', is_active=False,
        )
        response = self.client.get(reverse('training:manage_course_list'), {'active': 'yes'})
        self.assertEqual(list(response.context['courses']), [active_course])

    def test_search_filters_by_title_or_instructor(self):
        match_by_title = TrainingCourse.objects.create(
            title='Statistical Methods', description='...', price=10, duration='2 weeks', instructor='Dr. A',
        )
        match_by_instructor = TrainingCourse.objects.create(
            title='Research Writing', description='...', price=10, duration='2 weeks', instructor='Dr. Zawadi',
        )
        TrainingCourse.objects.create(
            title='Unrelated Course', description='...', price=10, duration='2 weeks', instructor='Dr. B',
        )
        response = self.client.get(reverse('training:manage_course_list'), {'q': 'statistical'})
        self.assertEqual(list(response.context['courses']), [match_by_title])

        response = self.client.get(reverse('training:manage_course_list'), {'q': 'zawadi'})
        self.assertEqual(list(response.context['courses']), [match_by_instructor])


@FAST_PASSWORD_HASHERS
class CourseEnrollmentsListTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='enrollments-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(email='enrollments-reader@example.com', password='pw', first_name='R', last_name='D')
        self.course = TrainingCourse.objects.create(
            title='Paginated Course', description='...', price=10, duration='2 weeks', instructor='Dr. P',
        )

    def test_non_editorial_cannot_view(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse('training:manage_course_enrollments', args=[self.course.pk]))
        self.assertEqual(response.status_code, 403)

    def test_editor_can_view_and_list_is_paginated(self):
        for i in range(35):
            user = User.objects.create_user(email=f'enrollee{i}@example.com', password='pw', first_name='E', last_name=str(i))
            Enrollment.objects.create(user=user, course=self.course, payment_status=Enrollment.PaymentStatus.PAID)

        self.client.force_login(self.editor)
        response = self.client.get(reverse('training:manage_course_enrollments', args=[self.course.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_paginated'])
        self.assertEqual(response.context['page_obj'].paginator.count, 35)
        self.assertEqual(len(response.context['page_obj']), 30)

    def test_filters_by_status_and_payment_status(self):
        active_paid = Enrollment.objects.create(
            user=self.reader, course=self.course,
            status=Enrollment.Status.ACTIVE, payment_status=Enrollment.PaymentStatus.PAID,
        )
        other_reader = User.objects.create_user(email='other-reader@example.com', password='pw', first_name='O', last_name='R')
        Enrollment.objects.create(
            user=other_reader, course=self.course,
            status=Enrollment.Status.CANCELLED, payment_status=Enrollment.PaymentStatus.REFUNDED,
        )
        self.client.force_login(self.editor)

        response = self.client.get(
            reverse('training:manage_course_enrollments', args=[self.course.pk]), {'status': Enrollment.Status.ACTIVE},
        )
        self.assertEqual(list(response.context['enrollments']), [active_paid])

        response = self.client.get(
            reverse('training:manage_course_enrollments', args=[self.course.pk]),
            {'payment_status': Enrollment.PaymentStatus.REFUNDED},
        )
        self.assertEqual(list(response.context['enrollments']), [Enrollment.objects.get(user=other_reader)])


@FAST_PASSWORD_HASHERS
class EnrollmentBulkUpdateTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='enrollment-bulk-editor@example.com', password='pw', first_name='E', last_name='D', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(email='enrollment-bulk-reader@example.com', password='pw', first_name='R', last_name='D')
        self.course = TrainingCourse.objects.create(
            title='Bulk Course', description='...', price=10, duration='2 weeks', instructor='Dr. B',
        )
        self.other_course = TrainingCourse.objects.create(
            title='Other Course', description='...', price=10, duration='2 weeks', instructor='Dr. C',
        )
        self.enrollment_a = Enrollment.objects.create(user=self.reader, course=self.course)
        other_reader = User.objects.create_user(email='enrollment-bulk-reader2@example.com', password='pw', first_name='O', last_name='R')
        self.enrollment_b = Enrollment.objects.create(user=other_reader, course=self.course)

    def test_bulk_update_sets_status_for_all_selected(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('training:manage_enrollment_bulk_update', args=[self.course.pk]), {
            'status': Enrollment.Status.COMPLETED, 'pks': [self.enrollment_a.pk, self.enrollment_b.pk],
        })
        self.enrollment_a.refresh_from_db()
        self.enrollment_b.refresh_from_db()
        self.assertEqual(self.enrollment_a.status, Enrollment.Status.COMPLETED)
        self.assertEqual(self.enrollment_b.status, Enrollment.Status.COMPLETED)

    def test_bulk_update_sets_payment_status_independently(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('training:manage_enrollment_bulk_update', args=[self.course.pk]), {
            'payment_status': Enrollment.PaymentStatus.PAID, 'pks': [self.enrollment_a.pk],
        })
        self.enrollment_a.refresh_from_db()
        self.assertEqual(self.enrollment_a.payment_status, Enrollment.PaymentStatus.PAID)
        self.assertEqual(self.enrollment_a.status, Enrollment.Status.ACTIVE)

    def test_bulk_update_ignores_enrollments_from_another_course(self):
        other_enrollment = Enrollment.objects.create(user=self.reader, course=self.other_course)
        self.client.force_login(self.editor)
        self.client.post(reverse('training:manage_enrollment_bulk_update', args=[self.course.pk]), {
            'status': Enrollment.Status.COMPLETED, 'pks': [other_enrollment.pk],
        })
        other_enrollment.refresh_from_db()
        self.assertEqual(other_enrollment.status, Enrollment.Status.ACTIVE)

    def test_no_change_when_neither_field_provided(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('training:manage_enrollment_bulk_update', args=[self.course.pk]), {
            'pks': [self.enrollment_a.pk],
        })
        self.assertRedirects(response, reverse('training:manage_course_enrollments', args=[self.course.pk]))
        self.enrollment_a.refresh_from_db()
        self.assertEqual(self.enrollment_a.status, Enrollment.Status.ACTIVE)

    def test_reader_cannot_bulk_update(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse('training:manage_enrollment_bulk_update', args=[self.course.pk]), {
            'status': Enrollment.Status.COMPLETED, 'pks': [self.enrollment_a.pk],
        })
        self.assertEqual(response.status_code, 403)


# The stub-gateway flow, whatever PAYMENT_GATEWAY a local .env sets.
@override_settings(PAYMENT_GATEWAY='stub')
class CourseCheckoutTests(TestCase):
    """Self-serve enroll-and-pay — StubGateway always succeeds (see
    billing/gateway.py) but the flow itself is real: no editorial action needed.
    """

    def setUp(self):
        self.reader = User.objects.create_user(
            email='enrollee@example.com', password='pw', first_name='E', last_name='N',
        )
        self.course = TrainingCourse.objects.create(
            title='Research Writing 101', description='...', price=25,
            duration='4 weeks', instructor='Dr. Rao',
        )

    def test_checkout_requires_login(self):
        response = self.client.get(reverse('training:course_checkout', args=[self.course.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_checkout_creates_paid_active_enrollment(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse('training:course_checkout', args=[self.course.pk]))
        self.assertEqual(response.status_code, 302)
        enrollment = Enrollment.objects.get(user=self.reader, course=self.course)
        self.assertEqual(enrollment.status, Enrollment.Status.ACTIVE)
        self.assertEqual(enrollment.payment_status, Enrollment.PaymentStatus.PAID)
        self.assertTrue(enrollment.payment_reference.startswith('stub-'))

    def test_full_course_blocks_checkout(self):
        self.course.max_enrollments = 1
        self.course.save(update_fields=['max_enrollments'])
        other = User.objects.create_user(email='other@example.com', password='pw', first_name='O', last_name='T')
        Enrollment.objects.create(
            user=other, course=self.course,
            payment_status=Enrollment.PaymentStatus.PAID, payment_reference='stub-existing',
        )

        self.client.force_login(self.reader)
        response = self.client.post(reverse('training:course_checkout', args=[self.course.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Enrollment.objects.filter(user=self.reader, course=self.course).exists())

    def test_already_enrolled_reader_not_double_charged(self):
        Enrollment.objects.create(
            user=self.reader, course=self.course,
            payment_status=Enrollment.PaymentStatus.PAID, payment_reference='stub-existing',
        )
        self.client.force_login(self.reader)
        response = self.client.post(reverse('training:course_checkout', args=[self.course.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Enrollment.objects.filter(user=self.reader, course=self.course).count(), 1)

    def test_declined_charge_shows_error_and_creates_no_enrollment(self):
        # Fault injection: StubGateway always succeeds today, so this
        # branch has never actually run — confirm it behaves correctly
        # before a real gateway starts returning real declines.
        self.client.force_login(self.reader)
        with patch('billing.gateway.get_gateway') as mock_get_gateway:
            mock_get_gateway.return_value.charge.return_value = PaymentResult(
                success=False, reference='', error='Card declined',
            )
            response = self.client.post(reverse('training:course_checkout', args=[self.course.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Card declined')
        self.assertFalse(Enrollment.objects.filter(user=self.reader, course=self.course).exists())

    def test_gateway_exception_is_treated_as_a_decline(self):
        # charge_safely() (billing/gateway.py) catches a raised exception
        # from the gateway call and converts it into the same declined-
        # payment path — no 500, no enrollment created.
        self.client.force_login(self.reader)
        with patch('billing.gateway.get_gateway') as mock_get_gateway:
            mock_get_gateway.return_value.charge.side_effect = ConnectionError('Gateway unreachable')
            response = self.client.post(reverse('training:course_checkout', args=[self.course.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment failed')
        self.assertFalse(Enrollment.objects.filter(user=self.reader, course=self.course).exists())


class CoursePublicPageMetaTagsTests(TestCase):
    def test_course_list_has_a_specific_title(self):
        response = self.client.get(reverse('training:course_list'))
        self.assertContains(response, '<title>Training Programs')

    def test_course_detail_title_and_description_reflect_the_course(self):
        course = TrainingCourse.objects.create(
            title='Clinical Data Analysis', description='Learn to analyze clinical trial data.',
            price=50, duration='6 weeks', instructor='Dr. Shah',
        )
        response = self.client.get(reverse('training:course_detail', args=[course.pk]))
        content = response.content.decode()
        self.assertIn('<title>Clinical Data Analysis', content)
        self.assertIn('Learn to analyze clinical trial data.', content)

    def test_course_detail_has_course_structured_data(self):
        course = TrainingCourse.objects.create(
            title='Systematic Reviews 101', description='How to conduct a systematic review.',
            price=75, duration='8 weeks', instructor='Dr. Bello',
        )
        response = self.client.get(reverse('training:course_detail', args=[course.pk]))
        content = response.content.decode()
        self.assertIn('"@type": "Course"', content)
        self.assertIn('"name": "Systematic Reviews 101"', content)
        self.assertIn('"price": "75.00"', content)
        self.assertIn('"priceCurrency": "NPR"', content)
        self.assertIn('"@type": "BreadcrumbList"', content)


class CourseCatalogFieldTests(TestCase):
    """Parsing helpers behind the course page's checklist/FAQ sections."""

    def test_line_fields_drop_blanks_and_typed_bullets(self):
        course = TrainingCourse(learning_outcomes='- Write an abstract\n\n• Pick a journal\n  * Respond to reviewers  ')
        self.assertEqual(course.learning_outcome_list, ['Write an abstract', 'Pick a journal', 'Respond to reviewers'])

    def test_faqs_split_on_blank_lines_and_skip_unanswered(self):
        course = TrainingCourse(faqs='Is it live?\nYes, weekly.\nRecorded too.\n\nOrphan question?\n\nCost?\nSee above.')
        self.assertEqual(course.faq_list, [
            {'question': 'Is it live?', 'answer': 'Yes, weekly. Recorded too.'},
            {'question': 'Cost?', 'answer': 'See above.'},
        ])

    def test_instructor_initial_skips_honorifics(self):
        self.assertEqual(TrainingCourse(instructor='Dr. Sunita Rai').instructor_initial, 'S')
        self.assertEqual(TrainingCourse(instructor='prof ram').instructor_initial, 'R')


def make_course(title, **fields):
    defaults = {'description': 'About.', 'price': 10, 'duration': '2 weeks', 'instructor': 'Dr. Rao'}
    defaults.update(fields)
    return TrainingCourse.objects.create(title=title, **defaults)


class CourseCatalogPageTests(TestCase):
    def test_filters_by_category_level_mode_and_search(self):
        writing = make_course('Writing', category='Research Writing', level=TrainingCourse.Level.BEGINNER)
        stats = make_course('Stats', category='Research Methods', mode=TrainingCourse.Mode.HYBRID)
        url = reverse('training:course_list')
        self.assertEqual(list(self.client.get(url, {'category': 'research writing'}).context['courses']), [writing])
        self.assertEqual(list(self.client.get(url, {'level': 'beginner'}).context['courses']), [writing])
        self.assertEqual(list(self.client.get(url, {'mode': 'hybrid'}).context['courses']), [stats])
        self.assertEqual(list(self.client.get(url, {'q': 'stat'}).context['courses']), [stats])

    def test_featured_course_only_on_unfiltered_catalog(self):
        featured = make_course('Flagship', is_featured=True)
        make_course('Other')
        url = reverse('training:course_list')
        self.assertEqual(self.client.get(url).context['featured_course'], featured)
        self.assertIsNone(self.client.get(url, {'q': 'other'}).context['featured_course'])

    def test_inactive_courses_hidden(self):
        make_course('Retired Zebra Course', is_active=False)
        response = self.client.get(reverse('training:course_list'))
        self.assertNotContains(response, 'Retired Zebra Course')
        self.assertEqual(response.context['catalog_stats']['courses'], 0)

    def test_detail_renders_outcomes_modules_faq_and_related(self):
        course = make_course(
            'Grant Writing', category='Writing', learning_outcomes='Draft a budget\nWrite aims',
            faqs='Is there homework?\nOne exercise a week.', instructor_title='Senior Editor',
        )
        course.modules.create(order=1, title='Second module')
        course.modules.create(order=0, title='First module', summary='Intro.')
        related = make_course('Report Writing', category='Writing')
        make_course('Unrelated')
        response = self.client.get(reverse('training:course_detail', args=[course.pk]))
        self.assertContains(response, 'Draft a budget')
        self.assertContains(response, 'Is there homework?')
        self.assertContains(response, 'Senior Editor')
        self.assertEqual([m.title for m in response.context['modules']], ['First module', 'Second module'])
        self.assertEqual(response.context['related_courses'][0], related)
        self.assertNotIn(course, response.context['related_courses'])


@FAST_PASSWORD_HASHERS
class CourseManageModulesTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='course-editor@example.com', password='pw', first_name='C', last_name='E', role=User.Role.EDITOR,
        )
        self.client.force_login(self.editor)

    def _data(self, **overrides):
        data = {
            'title': 'Data Visualisation', 'description': 'Charts.', 'price': '20', 'duration': '3 weeks',
            'instructor': 'Dr. Lama', 'level': 'beginner', 'mode': 'online', 'language': 'English',
            'is_active': 'on',
            'modules-TOTAL_FORMS': '2', 'modules-INITIAL_FORMS': '0',
            'modules-MIN_NUM_FORMS': '0', 'modules-MAX_NUM_FORMS': '1000',
            'modules-0-order': '0', 'modules-0-title': 'Chart types', 'modules-0-duration': 'Week 1',
            'modules-1-order': '0', 'modules-1-title': '',
        }
        data.update(overrides)
        return data

    def test_create_saves_course_and_filled_modules_only(self):
        response = self.client.post(reverse('training:manage_course_create'), self._data())
        self.assertEqual(response.status_code, 302)
        course = TrainingCourse.objects.get(title='Data Visualisation')
        self.assertEqual([m.title for m in course.modules.all()], ['Chart types'])

    def test_invalid_module_row_blocks_saving_the_course(self):
        response = self.client.post(reverse('training:manage_course_create'), self._data(**{
            'modules-1-order': '1', 'modules-1-title': '', 'modules-1-duration': 'Week 2',
        }))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TrainingCourse.objects.filter(title='Data Visualisation').exists())


@FAST_PASSWORD_HASHERS
class CourseManageListCountsTests(TestCase):
    def test_seat_counts_not_multiplied_by_module_count(self):
        editor = User.objects.create_user(
            email='count-editor@example.com', password='pw', first_name='C', last_name='E', role=User.Role.EDITOR,
        )
        learner = User.objects.create_user(email='count-learner@example.com', password='pw', first_name='L', last_name='N')
        course = make_course('Counted Course')
        for order in range(3):
            course.modules.create(order=order, title=f'Module {order}')
        Enrollment.objects.create(user=learner, course=course)
        self.client.force_login(editor)
        row = self.client.get(reverse('training:manage_course_list')).context['courses'][0]
        self.assertEqual((row.active_enrollment_count, row.enrollment_count, row.module_count), (1, 1, 3))
