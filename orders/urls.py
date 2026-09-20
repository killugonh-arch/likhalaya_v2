from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/<int:product_id>/', views.cart_add, name='cart_add'),
    path('cart/update/<str:item_key>/', views.cart_update, name='cart_update'),
    path('cart/remove/<str:item_key>/', views.cart_remove, name='cart_remove'),
    path('checkout/', views.checkout, name='checkout'),
    path('checkout/buy-now/cancel/', views.buy_now_cancel, name='buy_now_cancel'),
    path('checkout/select/', views.checkout_select, name='checkout_select'),
    path('checkout/review/', views.checkout_review, name='checkout_review'),
    path('checkout/gcash/', views.gcash_payment_pending, name='gcash_payment_pending'),
    path('checkout/gcash/qr-image/', views.gcash_qr_image_pending, name='gcash_qr_image_pending'),
    path('checkout/gcash/<int:pk>/', views.gcash_payment, name='gcash_payment'),
    path('checkout/gcash/<int:pk>/qr-image/', views.gcash_qr_image, name='gcash_qr_image'),
    path('checkout/gcash/<int:pk>/confirm/', views.gcash_finalize, name='gcash_finalize'),
    path('checkout/gcash/<int:pk>/back/', views.gcash_back_to_checkout, name='gcash_back_to_checkout'),
    path('confirmation/<int:pk>/', views.order_confirmation, name='order_confirmation'),
    path('my-orders/', views.my_orders, name='my_orders'),
    path('my-orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('my-orders/<int:pk>/cancel/', views.cancel_order, name='cancel_order'),
]