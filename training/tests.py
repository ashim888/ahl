from django.test import TestCase, override_settings
from django.urls import reverse

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
