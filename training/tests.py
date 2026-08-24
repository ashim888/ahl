from django.test import TestCase
from django.urls import reverse

from users.models import User

from .models import Enrollment, TrainingCourse


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
