"""
Email backend that sends through Brevo's HTTPS API (port 443).

Why: Render's free web services block outbound SMTP ports (25/465/587), so
Django's normal SMTP backend hangs until gunicorn kills the worker.
Plain HTTPS is not blocked. No extra package needed - uses urllib only.
"""
import json
import urllib.request
import urllib.error
from email.utils import parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'


class BrevoEmailBackend(BaseEmailBackend):

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        sent = 0
        for message in email_messages:
            try:
                self._send(message)
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return sent

    def _send(self, message):
        api_key = getattr(settings, 'BREVO_API_KEY', '')
        if not api_key:
            raise RuntimeError('BREVO_API_KEY is not set')

        name, addr = parseaddr(message.from_email or settings.DEFAULT_FROM_EMAIL)
        sender = {'email': addr}
        if name:
            sender['name'] = name

        payload = {
            'sender': sender,
            'to': [{'email': a} for a in message.to],
            'subject': message.subject,
        }
        if message.cc:
            payload['cc'] = [{'email': a} for a in message.cc]
        if message.bcc:
            payload['bcc'] = [{'email': a} for a in message.bcc]

        html = None
        for content, mimetype in getattr(message, 'alternatives', []):
            if mimetype == 'text/html':
                html = content
        if html is not None:
            payload['htmlContent'] = html
            payload['textContent'] = message.body
        elif getattr(message, 'content_subtype', 'plain') == 'html':
            payload['htmlContent'] = message.body
        else:
            payload['textContent'] = message.body

        req = urllib.request.Request(
            getattr(settings, 'BREVO_API_URL', BREVO_API_URL),
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'api-key': api_key,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            method='POST',
        )
        timeout = getattr(settings, 'EMAIL_TIMEOUT', None) or 10
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'replace')
            raise RuntimeError(f'Brevo API error {exc.code}: {detail}') from exc