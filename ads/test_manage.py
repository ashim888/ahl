"""Creating and editing an ad through /manage/ads/ end to end — the form
checks the image against the zone's size, so this is the path editors use."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import User

from .models import AdSlot
from .tests import demo_image, make_ad


def upload(size, name='banner.jpg'):
    return SimpleUploadedFile(name, demo_image(name, size).read(), content_type='image/jpeg')


class AdSlotFormViewTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email='ads-editor@example.com', password='pw', first_name='A', last_name='E', role=User.Role.EDITOR,
        )
        self.client.force_login(self.editor)

    def _data(self, **overrides):
        data = {
            'sponsor_name': 'Himalayan Pharma', 'zone': AdSlot.Zone.HOMEPAGE_RECTANGLE_1,
            'image': upload((300, 250)), 'link_url': 'https://sponsor.example/',
            'start_date': timezone.localdate().isoformat(), 'is_active': 'on',
        }
        data.update(overrides)
        return data

    def test_create_page_shows_where_every_zone_appears(self):
        page = self.client.get(reverse('ads:manage_adslot_create'))
        self.assertTrue(page.context['is_create'])
        info = page.context['zone_info']
        self.assertEqual(set(info), set(AdSlot.Zone.values))
        self.assertEqual((info[AdSlot.Zone.HOMEPAGE_RECTANGLE_1]['width'], info[AdSlot.Zone.HOMEPAGE_RECTANGLE_1]['height']),
                         (300, 250))
        self.assertEqual(info[AdSlot.Zone.MOBILE_ANCHOR]['screens'], 'Phones only')
        self.assertContains(page, 'id="zone-map"')
        for zone in AdSlot.Zone.values:  # every zone has a box in the picture
            self.assertContains(page, f'data-zone-pick="{zone}"')

    def test_running_count_leaves_out_the_ad_being_edited(self):
        ad = make_ad(zone=AdSlot.Zone.ARTICLE_SIDEBAR)
        make_ad(zone=AdSlot.Zone.ARTICLE_SIDEBAR, sponsor_name='Other')
        make_ad(zone=AdSlot.Zone.ARTICLE_SIDEBAR, sponsor_name='Stopped', is_active=False)
        page = self.client.get(reverse('ads:manage_adslot_update', args=[ad.pk]))
        info = page.context['zone_info']
        self.assertEqual(info[AdSlot.Zone.ARTICLE_SIDEBAR]['running'], 1)
        # The running ad is drawn into the layout picture: its name, image and an edit link.
        [running] = info[AdSlot.Zone.ARTICLE_SIDEBAR]['ads']
        self.assertEqual(running['sponsor'], 'Other')
        self.assertTrue(running['image'].endswith('.jpg'))
        self.assertIn('/edit/', running['edit_url'])
        self.assertEqual(info[AdSlot.Zone.MOBILE_ANCHOR]['ads'], [])
        self.assertContains(page, 'zone-box__badge')
        self.assertContains(page, 'data-zone-pick="article_sidebar" aria-pressed="true"')

    def test_create_with_the_right_size(self):
        response = self.client.post(reverse('ads:manage_adslot_create'), self._data(), follow=True)
        self.assertContains(response, '&quot;Himalayan Pharma&quot; ad created.')
        self.assertTrue(AdSlot.objects.filter(sponsor_name='Himalayan Pharma', zone=AdSlot.Zone.HOMEPAGE_RECTANGLE_1).exists())

    def test_wrong_size_is_refused(self):
        response = self.client.post(reverse('ads:manage_adslot_create'), self._data(image=upload((728, 90))))
        self.assertEqual(response.status_code, 200)
        self.assertIn('image', response.context['form'].errors)
        self.assertFalse(AdSlot.objects.exists())

    def test_edit_renames_the_sponsor(self):
        ad = make_ad(sponsor_name='Old Name')
        url = reverse('ads:manage_adslot_update', args=[ad.pk])
        self.assertFalse(self.client.get(url).context['is_create'])
        data = self._data(sponsor_name='New Name', image=upload((300, 250)))
        response = self.client.post(url, data, follow=True)
        self.assertContains(response, '&quot;New Name&quot; ad updated.')
        ad.refresh_from_db()
        self.assertEqual(ad.sponsor_name, 'New Name')

    def test_readers_cannot_create_ads(self):
        reader = User.objects.create_user(email='ads-reader@example.com', password='pw', first_name='R', last_name='A')
        self.client.force_login(reader)
        self.assertEqual(self.client.post(reverse('ads:manage_adslot_create'), self._data()).status_code, 403)
        self.assertFalse(AdSlot.objects.exists())
