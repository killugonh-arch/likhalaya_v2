import json
from datetime import timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q, Prefetch
from django.core.paginator import Paginator
from django.core.cache import cache
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from .models import Product, Category, Personnel, ContactMessage, LivelihoodVideo, ProductDesign, MessageReply
from .forms import ContactForm

# Cooldown between messages a customer sends in a conversation thread, to
# discourage spamming staff / flooding the thread. Applied per-thread.
MESSAGE_REPLY_COOLDOWN_SECONDS = 20

# How many of the most recent replies to render on first load of a thread;
# older ones are fetched on demand as the customer scrolls up (infinite scroll).
MESSAGE_THREAD_PAGE_SIZE = 15

# Server-side throttle for the infinite-scroll endpoint: real scrolling never
# needs more than a couple of calls per second, so this only blocks scripted
# hammering (the client-side `loading` flag is easy to bypass by calling the
# endpoint directly).
MESSAGE_OLDER_REPLIES_MAX_PER_WINDOW = 20
MESSAGE_OLDER_REPLIES_WINDOW_SECONDS = 10


def _customer_reply_cooldown_remaining(thread, user):
    """Seconds left before `user` may send another reply on `thread`, or 0
    if they're clear to send. Based on their own last reply in this thread."""
    # Counted across ALL of the customer's inquiries, since one reply can now
    # be sent on any of them (the "Reply" button on a message).
    last_reply = (
        MessageReply.objects.filter(thread__customer=user, is_staff_reply=False)
        .order_by('-created_at')
        .first()
    )
    if not last_reply:
        return 0
    elapsed = (timezone.now() - last_reply.created_at).total_seconds()
    remaining = MESSAGE_REPLY_COOLDOWN_SECONDS - elapsed
    return max(0, int(remaining) + (1 if remaining % 1 else 0))


def home(request):
    latest_products = Product.objects.filter(is_active=True).select_related('category').order_by('-created_at')[:8]
    categories = Category.objects.filter(is_active=True).order_by('order', 'name')
    active_videos = list(
        LivelihoodVideo.objects.filter(is_active=True, show_on_home=True).order_by('order', '-created_at')[:2]
    )
    featured_video = active_videos[0] if len(active_videos) > 0 else None
    second_video = active_videos[1] if len(active_videos) > 1 else None
    return render(request, 'store/home.html', {
        'latest_products': latest_products,
        'categories': categories,
        'featured_video': featured_video,
        'second_video': second_video,
    })


def shop(request):
    products = Product.objects.filter(is_active=True).select_related('category').prefetch_related(
        'extra_images'
    )
    search_query = request.GET.get('q', '').strip()
    selected_category = request.GET.get('category', '').strip()
    sort = request.GET.get('sort', '-created_at')
    in_stock_filter = request.GET.get('in_stock', '')

    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(artisan_name__icontains=search_query)
        )
    if selected_category:
        products = products.filter(category__slug=selected_category)
    if in_stock_filter:
        products = products.filter(stock__gt=0)

    sort_map = {
        'price_min': 'price_min', '-price_min': '-price_min',
        'name': 'name', '-name': '-name',
        '-created_at': '-created_at', 'created_at': 'created_at',
    }
    products = products.order_by(sort_map.get(sort, '-created_at'))

    paginator = Paginator(products, 12)
    page_obj = paginator.get_page(request.GET.get('page'))
    categories = Category.objects.filter(is_active=True).prefetch_related('products').order_by('order', 'name')

    return render(request, 'store/shop.html', {
        'products': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'categories': categories,
        'search_query': search_query,
        'selected_category': selected_category,
        'sort': sort,
        'in_stock_filter': in_stock_filter,
    })


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.prefetch_related('extra_images', 'sizes__designs'), slug=slug, is_active=True
    )
    related_products = Product.objects.filter(
        category=product.category, is_active=True
    ).exclude(pk=product.pk)[:4]
    return render(request, 'store/product_detail.html', {
        'product': product,
        'related_products': related_products,
    })


def category_view(request, slug):
    category = get_object_or_404(Category, slug=slug, is_active=True)
    products = Product.objects.filter(category=category, is_active=True).select_related('category')
    paginator = Paginator(products, 12)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'store/category.html', {
        'category': category,
        'products': page_obj,
        'page_obj': page_obj,
    })


def about(request):
    personnel = Personnel.objects.filter(is_active=True)
    videos = LivelihoodVideo.objects.filter(is_active=True).order_by('order', '-created_at')
    return render(request, 'store/about.html', {'personnel': personnel, 'videos': videos})


def contact(request):
    # Visitors who aren't logged in can still see the contact details;
    # only sending a message requires an account.
    if not request.user.is_authenticated:
        return render(request, 'store/contact_guest.html', {'next': request.get_full_path()})

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    context_product = None

    if request.method == 'POST':
        # Honeypot — see accounts.views.login_view for why this fakes a
        # normal success instead of returning any error to the bot.
        if request.POST.get('website'):
            fake_message = (
                'Thank you! Your request has been received. Our team will review your inquiry '
                'and reply here on the site. Check My Messages for updates.'
            )
            if is_ajax:
                return JsonResponse({'ok': True, 'message': fake_message})
            messages.success(request, fake_message)
            return redirect('store:contact')
        form = ContactForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            msg = form.save(commit=False)
            msg.customer = request.user
            msg.save()
            success_message = (
                'Thank you! Your request has been received. Our team will review your inquiry '
                'and reply here on the site. Check My Messages for updates.'
            )
            if is_ajax:
                return JsonResponse({'ok': True, 'message': success_message})
            messages.success(request, success_message)
            return redirect('store:my_message_detail', pk=msg.pk)

        if is_ajax:
            return JsonResponse({'ok': False, 'errors': form.errors}, status=400)
        product_id = request.POST.get('product')
        if product_id:
            context_product = Product.objects.filter(pk=product_id).first()
    else:
        initial = {
            'name': request.user.get_full_name(),
            'email': request.user.email,
        }
        if request.user.phone:
            initial['phone'] = request.user.phone
        # Location from the profile address fields (blank if none saved)
        location_str = ContactForm.profile_location(request.user)
        if location_str:
            initial['location'] = location_str

        # Opened from a product page ("Ask about this product") — auto-populate
        # the product reference and item name, and pre-select the merged
        # "Product & Custom Orders" category, without forcing the customer to
        # type the product name manually.
        product_id = request.GET.get('product')
        if product_id:
            context_product = Product.objects.filter(pk=product_id, is_active=True).first()
            if context_product:
                initial['product'] = context_product.pk
                initial['item_name'] = context_product.name
                initial['inquiry_type'] = ContactMessage.INQUIRY_CUSTOM_ORDER
                initial['subject'] = f'Product & Custom Order Inquiry — {context_product.name}'

        form = ContactForm(initial=initial, user=request.user)
    return render(request, 'store/contact.html', {'form': form, 'context_product': context_product})


def _parse_quote(raw):
    """Turn a stored MessageReply.quoted_text into {subject, body, time}.
    Older replies stored plain text only, so fall back to that."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {
                'subject': data.get('s', ''),
                'body': data.get('b', ''),
                'time': data.get('t', ''),
            }
    except (ValueError, TypeError):
        pass
    return {'subject': '', 'body': raw, 'time': ''}


def _inquiry_details(t):
    """The extra info the customer filled in on the Contact form for this
    inquiry, as (label, value) pairs — empty fields are left out."""
    order_ref = t.order_number_ref or (t.order.order_number if t.order_id and getattr(t.order, 'order_number', None) else '')
    rows = [
        ('Product', t.product.name if t.product_id else ''),
        ('Order', order_ref),
        ('Item', t.item_name),
        ('Quantity', t.quantity),
        ('Customization', t.customization_request),
        ('Preferred materials', t.preferred_materials),
        ('Target budget', t.target_budget),
        ('Preferred date', t.preferred_date.strftime('%b %d, %Y') if t.preferred_date else ''),
        ('Organization', t.organization_name),
        ('Materials condition', t.get_materials_condition_display() if t.materials_condition else ''),
        ('Partnership type', t.get_partnership_type_display() if t.partnership_type else ''),
        ('Partnership details', t.partnership_details),
        ('Feedback type', t.get_feedback_type_display() if t.feedback_type else ''),
        ('Related product', t.related_product),
        ('Concern type', t.get_concern_type_display() if t.concern_type else ''),
        ('Additional details', t.additional_details),
    ]
    return [(label, value) for label, value in rows if value]


@login_required
def my_messages(request):
    """Customer-facing messages: ONE combined conversation covering every
    inquiry the customer has sent, in chronological order. Replies are sent
    in-site (no email) and attach to the customer's most recent inquiry.
    Message bodies are stored encrypted (see store/fields.py)."""
    threads = list(
        ContactMessage.objects.filter(customer=request.user)
        .select_related('product', 'order')
        .order_by('created_at')
        .prefetch_related('replies')
    )
    latest = threads[-1] if threads else None

    if request.method == 'POST':
        if latest is None:
            return redirect('store:contact')
        body = request.POST.get('body', '').strip()
        cooldown_remaining = _customer_reply_cooldown_remaining(latest, request.user)
        if cooldown_remaining > 0:
            messages.error(
                request,
                f'Please wait {cooldown_remaining}s before sending another message.'
            )
        elif body:
            # "Reply" button on a message: the reply goes on that message's
            # inquiry (only the customer's own), with a snapshot of the quoted
            # message. Without it, it goes on the most recent inquiry as before.
            target = latest
            quoted_text = ''
            reply_to = request.POST.get('reply_to', '').strip()
            if reply_to.isdigit():
                target = next((t for t in threads if t.pk == int(reply_to)), latest)
                quoted_text = json.dumps({
                    's': target.subject,
                    'b': request.POST.get('reply_quote', '').strip()[:300],
                    't': request.POST.get('reply_quote_time', '').strip()[:40],
                })
            MessageReply.objects.create(
                thread=target,
                is_staff_reply=False,
                quoted_text=quoted_text,
                body=body,
                is_read_by_customer=True,
                is_read_by_staff=False,
            )
            latest = target
            # Flag the thread as unread so the admin bell, the unread count and
            # the Messages list light up for this new customer reply.
            update_fields = ['is_read']
            latest.is_read = False
            if latest.status in (ContactMessage.STATUS_RESOLVED, ContactMessage.STATUS_CLOSED):
                latest.status = ContactMessage.STATUS_UNDER_REVIEW
                update_fields.append('status')
            latest.save(update_fields=update_fields)
            messages.success(request, 'Your reply has been sent.')
        return redirect('store:my_messages')

    has_unread = any(t.has_unread_for_customer for t in threads)

    # Merge every inquiry + its replies into one chronological timeline.
    timeline = []
    for t in threads:
        timeline.append({
            'is_staff_reply': False,
            'body': t.message,
            'created_at': t.created_at,
            'thread_pk': t.pk,
            'subject': t.subject,
            'inquiry_type': t.inquiry_type,
            'type_display': t.get_inquiry_type_display(),
            'starts_thread': True,
            'details': _inquiry_details(t),
            'image_url': t.reference_image.url if t.reference_image else '',
            'quote': None,
            'seen': t.is_read,
        })
        for r in t.replies.all():
            timeline.append({
                'is_staff_reply': r.is_staff_reply,
                'body': r.body,
                'created_at': r.created_at,
                'thread_pk': t.pk,
                'subject': t.subject,
                'starts_thread': False,
                'quote': _parse_quote(r.quoted_text),
                'seen': r.is_read_by_staff,
            })
    timeline.sort(key=lambda e: e['created_at'])

    # The "Reply" button only shows on messages from the last 6 hours.
    reply_cutoff = timezone.now() - timedelta(hours=6)
    for e in timeline:
        e['can_reply'] = e['created_at'] >= reply_cutoff

    # Group back-to-back messages from the same sender sent within 5 minutes of
    # the previous one: the name shows once (first), the avatar and the time
    # show only on the last message of the group. A new inquiry always starts
    # a new group.
    prev = None
    for e in timeline:
        e['is_continuation'] = bool(
            prev
            and not e['starts_thread']
            and prev['is_staff_reply'] == e['is_staff_reply']
            and (e['created_at'] - prev['created_at']).total_seconds() <= 300
        )
        prev = e
    for i, e in enumerate(timeline):
        nxt = timeline[i + 1] if i + 1 < len(timeline) else None
        e['show_time'] = not (nxt and nxt['is_continuation'])

    # Mark staff replies as read now that the customer is viewing the conversation.
    MessageReply.objects.filter(
        thread__customer=request.user, is_staff_reply=True, is_read_by_customer=False
    ).update(is_read_by_customer=True)

    return render(request, 'store/my_messages.html', {
        'threads': threads,
        'timeline': timeline,
        'has_unread': has_unread,
        'first_thread': threads[0] if threads else None,
        'cooldown_remaining': _customer_reply_cooldown_remaining(latest, request.user) if latest else 0,
    })


@login_required
def my_message_detail(request, pk):
    """Old per-thread URL (still used by notification links): everything now
    lives in the single combined conversation."""
    get_object_or_404(ContactMessage, pk=pk, customer=request.user)
    return redirect('store:my_messages')


@login_required
def my_message_older_replies(request, pk):
    """AJAX endpoint powering infinite scroll on the thread view: returns the
    page of replies immediately older than `before_id`."""
    # Throttle: cheap, fixed-size window cache counter per user.
    throttle_key = f'msg_older_throttle:{request.user.pk}'
    request_count = cache.get(throttle_key, 0)
    if request_count >= MESSAGE_OLDER_REPLIES_MAX_PER_WINDOW:
        return JsonResponse({'error': 'Too many requests, slow down.'}, status=429)
    cache.set(throttle_key, request_count + 1, MESSAGE_OLDER_REPLIES_WINDOW_SECONDS)

    thread = get_object_or_404(ContactMessage, pk=pk, customer=request.user)

    before_id = request.GET.get('before_id', '')
    if not before_id.isdigit():
        return JsonResponse({'replies': [], 'has_more': False})

    older = thread.replies.filter(id__lt=before_id).order_by('-created_at')[:MESSAGE_THREAD_PAGE_SIZE]
    older = list(reversed(older))  # chronological order for prepending
    has_more = thread.replies.filter(id__lt=older[0].id).exists() if older else False

    return JsonResponse({
        'replies': [{
            'id': r.id,
            'is_staff_reply': r.is_staff_reply,
            'sender_label': 'Likhalaya Team' if r.is_staff_reply else 'You',
            'body': r.body,
            'created_at': timezone.localtime(r.created_at).strftime('%b %d, %Y %H:%M'),
        } for r in older],
        'has_more': has_more,
    })


def terms(request):
    return render(request, 'store/terms.html')