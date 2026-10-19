from django import template
from django.core.paginator import Paginator
from django.db.models import Avg, Count
from django.utils.html import format_html, format_html_join

from reviews.models import Review, review_stats, star_list, user_has_purchased

register = template.Library()

PER_PAGE = 5
SORTS = {
    'newest': '-created_at',
    'highest': '-rating',
    'lowest': 'rating',
}


@register.inclusion_tag('partials/rating_summary.html')
def rating_summary(product):
    """Compact ★★★★☆ 4.5 (12 reviews) line — links to #reviews."""
    return {'stats': review_stats(product), 'product': product}


@register.inclusion_tag('partials/product_reviews.html', takes_context=True)
def product_reviews(context, product):
    """Full reviews section for the product page: summary, list, and the
    add/edit form for logged-in customers."""
    request = context['request']
    user = request.user

    sort = request.GET.get('rsort', 'newest')
    if sort not in SORTS:
        sort = 'newest'
    order = [SORTS[sort], '-created_at']

    qs = Review.objects.filter(product=product, is_visible=True).order_by(*order)
    page_obj = Paginator(qs, PER_PAGE).get_page(request.GET.get('rpage'))

    my_review = None
    if user.is_authenticated:
        my_review = Review.objects.filter(product=product, user=user).first()

    return {
        'request': request,
        'user': user,
        'product': product,
        'stats': review_stats(product),
        'page_obj': page_obj,
        'sort': sort,
        'my_review': my_review,
        'has_purchased': user_has_purchased(user, product),
    }



ICONS = {
    'full': 'fas fa-star',
    'half': 'fas fa-star-half-stroke',
    'empty': 'far fa-star',
}


@register.simple_tag
def card_rating(product):
    """Inline star row for product cards (shop, home, category).
    Renders its own HTML with inline styles, so it needs no template file.
    Not a link, so it never fights the card's stretched-link."""
    agg = Review.objects.filter(product=product, is_visible=True).aggregate(
        avg=Avg('rating'), total=Count('id'))
    total = agg['total'] or 0
    average = round(float(agg['avg'] or 0), 1)

    stars = format_html_join(
        '', '<i class="{}"></i>', ((ICONS[s],) for s in star_list(average)))

    if total:
        tip = f"{average} out of 5 · {total} review{'s' if total != 1 else ''}"
        label = format_html(
            '<span style="font-size:12px;font-weight:700;color:#2b2b2b;">{}</span>'
            '<span style="font-size:11px;color:#8a8a8a;">({})</span>',
            average, total)
    else:
        tip = 'No reviews yet'
        label = format_html('<span style="font-size:11px;color:#8a8a8a;">No reviews yet</span>')

    return format_html(
        '<div title="{}" style="display:flex;align-items:center;gap:5px;line-height:1;'
        'margin:1px 0 2px;position:relative;z-index:2;pointer-events:none;">'
        '<span aria-hidden="true" style="color:#E0A82E;font-size:11.5px;letter-spacing:1px;'
        'white-space:nowrap;">{}</span>{}</div>',
        tip, stars, label)