from .models import Category

def cart_count(request):
    from orders.cart import Cart
    cart = Cart(request)
    return {'cart_count': cart.product_count()}

def categories_ctx(request):
    return {'nav_categories': Category.objects.filter(is_active=True)}