from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.activity import log_activity
from dashboard.views import staff_required, admin_required, _safe_next
from store.models import Product

from .forms import ReviewReplyForm
from .models import Review


@staff_required
def review_list(request):
    qs = Review.objects.select_related('product', 'user').order_by('-created_at')

    search = request.GET.get('q', '').strip()
    rating = request.GET.get('rating', '')
    status = request.GET.get('status', '')
    product_id = request.GET.get('product', '')

    if search:
        qs = qs.filter(
            Q(product__name__icontains=search)
            | Q(reviewer_name__icontains=search)
            | Q(user__email__icontains=search)
            | Q(comment__icontains=search)
        )
    if rating in {'1', '2', '3', '4', '5'}:
        qs = qs.filter(rating=int(rating))
    if status == 'visible':
        qs = qs.filter(is_visible=True)
    elif status == 'hidden':
        qs = qs.filter(is_visible=False)
    elif status == 'unreplied':
        qs = qs.filter(staff_reply='')
    elif status == 'verified':
        qs = qs.filter(is_verified_purchase=True)
    if product_id.isdigit():
        qs = qs.filter(product_id=int(product_id))

    overall = Review.objects.aggregate(
        total=Count('id'),
        avg=Avg('rating', filter=Q(is_visible=True)),
        hidden=Count('id', filter=Q(is_visible=False)),
        unreplied=Count('id', filter=Q(staff_reply='')),
    )

    page_obj = Paginator(qs, 15).get_page(request.GET.get('page'))

    # keep filters when paging
    params = request.GET.copy()
    params.pop('page', None)

    return render(request, 'dashboard/reviews/list.html', {
        'reviews': page_obj,
        'page_obj': page_obj,
        'search': search,
        'rating_filter': rating,
        'status_filter': status,
        'product_filter': product_id,
        'products': Product.all_objects.filter(reviews__isnull=False).distinct().order_by('name'),
        'overall': {
            'total': overall['total'] or 0,
            'avg': round(overall['avg'] or 0, 1),
            'hidden': overall['hidden'] or 0,
            'unreplied': overall['unreplied'] or 0,
        },
        'querystring': params.urlencode(),
    })


@staff_required
@require_POST
def review_toggle_visible(request, pk):
    review = get_object_or_404(Review.objects.select_related('product'), pk=pk)
    review.is_visible = not review.is_visible
    review.save(update_fields=['is_visible', 'updated_at'])
    state = 'visible' if review.is_visible else 'hidden'
    log_activity(
        request, 'update',
        f'Set review on "{review.product.name}" to {state}',
        resource='Review', resource_label=f'{review.display_name} – {review.product.name}',
        previous_value='hidden' if review.is_visible else 'visible', new_value=state,
    )
    messages.success(request, f'Review is now {state}.')
    return redirect(_safe_next(request, request.POST.get('next'), 'reviews:dashboard_list'))


@staff_required
@require_POST
def review_reply(request, pk):
    review = get_object_or_404(Review.objects.select_related('product'), pk=pk)
    form = ReviewReplyForm(request.POST)
    if form.is_valid():
        text = form.cleaned_data['staff_reply']
        had_reply = bool(review.staff_reply)
        review.staff_reply = text
        review.replied_by = request.user if text else None
        review.replied_at = timezone.now() if text else None
        review.save(update_fields=['staff_reply', 'replied_by', 'replied_at', 'updated_at'])
        if text:
            action = 'Updated reply to' if had_reply else 'Replied to'
            log_activity(request, 'update', f'{action} review on "{review.product.name}"',
                         resource='Review', resource_label=f'{review.display_name} – {review.product.name}')
            messages.success(request, 'Reply saved.')
        else:
            log_activity(request, 'update', f'Removed reply on review for "{review.product.name}"',
                         resource='Review', resource_label=f'{review.display_name} – {review.product.name}')
            messages.success(request, 'Reply removed.')
    else:
        messages.error(request, 'Reply is too long (max 1000 characters).')
    return redirect(_safe_next(request, request.POST.get('next'), 'reviews:dashboard_list'))


@admin_required
@require_POST
def review_delete(request, pk):
    """Moves the review to the Archive (soft delete)."""
    review = get_object_or_404(Review.objects.select_related('product'), pk=pk)
    label = f'{review.display_name} – {review.product.name}'
    product_name = review.product.name
    review.archive(by_user=request.user)
    log_activity(request, 'delete', f'Archived review on "{product_name}"',
                 resource='Review', resource_label=label)
    messages.success(request, 'Review moved to the Archive.')
    return redirect(_safe_next(request, request.POST.get('next'), 'reviews:dashboard_list'))


@admin_required
@require_POST
def review_restore(request, pk):
    review = get_object_or_404(Review.all_objects.select_related('product'), pk=pk, is_deleted=True)
    label = f'{review.display_name} – {review.product.name}'
    review.restore()
    log_activity(request, 'restore', f'Restored review on "{review.product.name}"',
                 resource='Review', resource_label=label)
    messages.success(request, 'Review restored.')
    return redirect(f"{reverse('dashboard:archive')}?tab=reviews")


@admin_required
@require_POST
def review_delete_permanent(request, pk):
    review = get_object_or_404(Review.all_objects.select_related('product'), pk=pk, is_deleted=True)
    label = f'{review.display_name} – {review.product.name}'
    product_name = review.product.name
    review.delete()
    log_activity(request, 'delete', f'Permanently deleted review on "{product_name}"',
                 resource='Review', resource_label=label)
    messages.success(request, 'Review permanently deleted.')
    return redirect(f"{reverse('dashboard:archive')}?tab=reviews")