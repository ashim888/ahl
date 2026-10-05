"""Training gaps not in training/tests.py: course list filters, editing and
deleting a course, the per-enrollment status edit, re-enrolling after a
cancellation, and the course page's signed-in/related/cover details."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from users.models import User

from .models import Enrollment, TrainingCourse

# 1×1 PNG.
PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
    b'\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82'
)


def make_course(**extra):
    data = {'title': 'Research Writing', 'description': 'About.', 'price': 2900, 'duration': '4 weeks', 'instructor': 'Dr. Rao'}
    data.update(extra)
    return TrainingCourse.objects.create(**data)


class CourseManageTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='training-editor@example.com', password='pw', first_name='T', last_name='E', role=User.Role.EDITOR,
        )
        self.reader = User.objects.create_user(email='training-reader@example.com', password='pw', first_name='T', last_name='R')
        self.course = make_course()
        self.client.force_login(self.editor)

    def test_list_filters_by_active_and_search(self):
        hidden = make_course(title='Old Statistics', instructor='Dr. Shrestha', is_active=False)
        url = reverse('training:manage_course_list')
        self.assertEqual(list(self.client.get(url, {'active': 'yes'}).context['object_list']), [self.course])
        self.assertEqual(list(self.client.get(url, {'active': 'no'}).context['object_list']), [hidden])
        self.assertEqual(list(self.client.get(url, {'q': 'shrestha'}).context['object_list']), [hidden])

    def test_edit_course(self):
        url = reverse('training:manage_course_update', args=[self.course.pk])
        self.assertFalse(self.client.get(url).context['is_create'])
        response = self.client.post(url, {
            'title': 'Research Writing II', 'description': 'About.', 'price': '3100', 'duration': '5 weeks',
            'instructor': 'Dr. Rao', 'level': 'beginner', 'mode': 'online', 'language': 'English', 'is_active': 'on',
            'modules-TOTAL_FORMS': '0', 'modules-INITIAL_FORMS': '0', 'modules-MIN_NUM_FORMS': '0', 'modules-MAX_NUM_FORMS': '1000',
        })
        self.assertRedirects(response, reverse('training:manage_course_list'), fetch_redirect_response=False)
        self.course.refresh_from_db()
        self.assertEqual((self.course.title, str(self.course.price)), ('Research Writing II', '3100.00'))

    def test_delete_course(self):
        response = self.client.post(reverse('training:manage_course_delete', args=[self.course.pk]), follow=True)
        self.assertContains(response, '&quot;Research Writing&quot; deleted.')
        self.assertFalse(TrainingCourse.objects.filter(pk=self.course.pk).exists())

    def test_enrollment_update_sets_status_and_payment(self):
        enrollment = Enrollment.objects.create(user=self.reader, course=self.course)
        url = reverse('training:manage_enrollment_update', args=[enrollment.pk])
        response = self.client.post(url, {'status': Enrollment.Status.COMPLETED, 'payment_status': Enrollment.PaymentStatus.PAID})
        self.assertRedirects(response, reverse('training:manage_course_enrollments', args=[self.course.pk]), fetch_redirect_response=False)
        enrollment.refresh_from_db()
        self.assertEqual((enrollment.status, enrollment.payment_status), (Enrollment.Status.COMPLETED, Enrollment.PaymentStatus.PAID))

    def test_enrollment_update_ignores_unknown_values(self):
        enrollment = Enrollment.objects.create(user=self.reader, course=self.course)
        self.client.post(reverse('training:manage_enrollment_update', args=[enrollment.pk]), {'status': 'vip', 'payment_status': 'free'})
        enrollment.refresh_from_db()
        self.assertEqual((enrollment.status, enrollment.payment_status), (Enrollment.Status.ACTIVE, Enrollment.PaymentStatus.PENDING))

    def test_readers_cannot_mark_themselves_paid(self):
        enrollment = Enrollment.objects.create(user=self.reader, course=self.course)
        url = reverse('training:manage_enrollment_update', args=[enrollment.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.post(url, {'payment_status': Enrollment.PaymentStatus.PAID}).status_code, 403)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.payment_status, Enrollment.PaymentStatus.PENDING)


@override_settings(PAYMENT_GATEWAY='stub')
class CourseReaderTests(TestCase):
    def setUp(self):
        self.reader = User.objects.create_user(email='learner@example.com', password='pw', first_name='L', last_name='R')
        self.course = make_course(category='Research')

    def test_re_enrolling_after_cancelling_reuses_the_row(self):
        enrollment = Enrollment.objects.create(
            user=self.reader, course=self.course, status=Enrollment.Status.CANCELLED,
            payment_status=Enrollment.PaymentStatus.REFUNDED,
        )
        self.client.force_login(self.reader)
        self.client.post(reverse('training:course_checkout', args=[self.course.pk]))
        self.assertEqual(Enrollment.objects.filter(user=self.reader, course=self.course).count(), 1)
        enrollment.refresh_from_db()
        self.assertEqual((enrollment.status, enrollment.payment_status), (Enrollment.Status.ACTIVE, Enrollment.PaymentStatus.PAID))
        self.assertTrue(enrollment.payment_reference)

    def test_inactive_course_cannot_be_bought(self):
        self.course.is_active = False
        self.course.save()
        self.client.force_login(self.reader)
        self.assertEqual(self.client.post(reverse('training:course_checkout', args=[self.course.pk])).status_code, 404)
        self.assertFalse(Enrollment.objects.exists())

    def test_course_page_shows_the_readers_enrollment_and_same_category_first(self):
        same = make_course(title='Systematic Reviews', category='research')
        make_course(title='Podcasting', category='Media', is_featured=True)
        Enrollment.objects.create(user=self.reader, course=self.course)
        self.client.force_login(self.reader)
        response = self.client.get(reverse('training:course_detail', args=[self.course.pk]))
        self.assertEqual(response.context['enrollment'].user, self.reader)
        self.assertEqual(response.context['related_courses'][0], same)

    def test_cover_image_is_the_share_image(self):
        self.course.cover_image = SimpleUploadedFile('cover.png', PNG, content_type='image/png')
        self.course.save()
        response = self.client.get(reverse('training:course_detail', args=[self.course.pk]))
        self.assertTrue(response.context['meta_image_url'].startswith('http://testserver/'))
        self.assertContains(response, f'og:image" content="{response.context["meta_image_url"]}')
