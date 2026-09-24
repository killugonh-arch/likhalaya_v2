from django.contrib import admin

from .models import ChatMessage, Conversation


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    fields = ('from_customer', 'sender', 'body', 'read', 'created_at')
    readonly_fields = ('created_at',)
    raw_id_fields = ('sender',)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'created_at', 'message_count', 'unread_count')
    search_fields = ('customer__username', 'customer__email')
    raw_id_fields = ('customer',)
    inlines = [ChatMessageInline]

    @admin.display(description='Messages')
    def message_count(self, obj):
        return obj.messages.count()

    @admin.display(description='Unread (staff)')
    def unread_count(self, obj):
        return obj.unread_for_staff


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'from_customer', 'sender', 'short_body', 'read', 'created_at')
    list_filter = ('from_customer', 'read', 'created_at')
    search_fields = ('body', 'conversation__customer__username')
    raw_id_fields = ('conversation', 'sender')

    @admin.display(description='Body')
    def short_body(self, obj):
        return obj.body[:60]