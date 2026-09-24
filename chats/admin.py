from django.contrib import admin

from .models import ChatMessage, Conversation


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    fields = ('sender', 'body', 'read_at', 'created_at')
    readonly_fields = ('created_at',)
    raw_id_fields = ('sender',)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'created_at', 'message_count', 'unread_for_staff')
    search_fields = ('customer__username', 'customer__email')
    raw_id_fields = ('customer',)
    inlines = [ChatMessageInline]

    @admin.display(description='Messages')
    def message_count(self, obj):
        return obj.messages.count()

    @admin.display(description='Unread (staff)')
    def unread_for_staff(self, obj):
        return obj.messages.filter(read_at__isnull=True, sender=obj.customer).count()


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'is_from_customer', 'sender', 'short_body', 'is_read', 'created_at')
    list_filter = ('read_at', 'created_at')
    search_fields = ('body', 'conversation__customer__username', 'conversation__customer__email')
    raw_id_fields = ('conversation', 'sender')

    @admin.display(description='Body')
    def short_body(self, obj):
        return obj.body[:60]

    @admin.display(description='From customer', boolean=True)
    def is_from_customer(self, obj):
        return obj.from_customer

    @admin.display(description='Read', boolean=True)
    def is_read(self, obj):
        return obj.read_at is not None