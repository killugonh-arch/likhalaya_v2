from django.test import TestCase
from django.urls import reverse

from store.models import ContactMessage


class ContactMessageTests(TestCase):
    def test_contact_form_saves_message_and_redirects(self):
        response = self.client.post(reverse('store:contact'), {
            'name': 'Maria',
            'email': 'maria@example.com',
            'subject': 'Inquiry',
            'message': 'I would like to know more about your crafts.',
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(ContactMessage.objects.filter(email='maria@example.com').exists())
