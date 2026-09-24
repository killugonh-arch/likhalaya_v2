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
    last_reply = (
        MessageReply.objects.filter(thread=thread, is_staff_reply=False)
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
                'and reply here on the site — check My Messages for updates.'
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
                'and reply here on the site — check My Messages for updates.'
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


@login_required
def my_messages(request):
    """Customer-facing inbox: every inquiry the logged-in customer has sent,
    with an unread indicator when staff has replied."""
    threads = (
        ContactMessage.objects.filter(customer=request.user)
        .prefetch_related('replies')
        .order_by('-created_at')
    )
    return render(request, 'store/my_messages.html', {'threads': threads})


@login_required
def my_message_detail(request, pk):
    """Customer-facing conversation thread for one inquiry — reply in-site,
    no email involved. Message bodies are stored encrypted (see store/fields.py)."""
    thread = get_object_or_404(ContactMessage, pk=pk, customer=request.user)

    if request.method == 'POST':
        body = request.POST.get('body', '').strip()
        cooldown_remaining = _customer_reply_cooldown_remaining(thread, request.user)
        if cooldown_remaining > 0:
            messages.error(
                request,
                f'Please wait {cooldown_remaining}s before sending another message.'
            )
        elif body:
            MessageReply.objects.create(
                thread=thread,
                is_staff_reply=False,
                body=body,
                is_read_by_customer=True,
                is_read_by_staff=False,
            )
            if thread.status in (ContactMessage.STATUS_RESOLVED, ContactMessage.STATUS_CLOSED):
                thread.status = ContactMessage.STATUS_UNDER_REVIEW
                thread.save(update_fields=['status'])
            messages.success(request, 'Your reply has been sent.')
        return redirect('store:my_message_detail', pk=pk)

    # Mark staff replies as read now that the customer is viewing the thread.
    thread.replies.filter(is_staff_reply=True, is_read_by_customer=False).update(is_read_by_customer=True)

    # Infinite scroll: only render the most recent page of replies up front;
    # older ones load on demand as the customer scrolls up in the thread.
    all_reply_ids = list(thread.replies.order_by('created_at').values_list('id', flat=True))
    initial_ids = all_reply_ids[-MESSAGE_THREAD_PAGE_SIZE:]
    has_more = len(all_reply_ids) > len(initial_ids)
    initial_replies = thread.replies.filter(id__in=initial_ids).order_by('created_at')

    return render(request, 'store/my_message_detail.html', {
        'thread': thread,
        'replies': initial_replies,
        'has_more_replies': has_more,
        'oldest_loaded_reply_id': initial_ids[0] if initial_ids else None,
        'cooldown_remaining': _customer_reply_cooldown_remaining(thread, request.user),
    })


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