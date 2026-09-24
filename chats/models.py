from django.conf import settings
from django.db import models


class Conversation(models.Model):
    """One ongoing thread per customer with the Likhalaya team.
    Created lazily the first time the customer (or staff, replying to them)
    touches the chat endpoints."""
    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_conversation',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Conversation with {self.customer}"

    @property
    def last_message(self):
        return self.messages.order_by('-created_at').first()

    @property
    def unread_for_staff(self):
        return self.messages.filter(from_customer=True, read=False).count()


class ChatMessage(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        help_text='The staff member who sent this, when from_customer=False. Null for customer messages.',
    )
    from_customer = models.BooleanField(default=True)
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(
        default=False,
        help_text='Whether the *other* side has seen this message '
                   '(staff has read a customer message, or vice versa).',
    )

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        who = 'customer' if self.from_customer else (self.sender or 'staff')
        return f"[{self.conversation_id}] {who}: {self.body[:40]}"