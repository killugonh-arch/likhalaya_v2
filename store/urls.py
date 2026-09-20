from django.urls import path
from . import views

app_name = 'store'

urlpatterns = [
    path('', views.home, name='home'),
    path('shop/', views.shop, name='shop'),
    path('shop/<slug:slug>/', views.product_detail, name='product_detail'),
    path('category/<slug:slug>/', views.category_view, name='category'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('messages/', views.my_messages, name='my_messages'),
    path('messages/<int:pk>/', views.my_message_detail, name='my_message_detail'),
    path('messages/<int:pk>/older/', views.my_message_older_replies, name='my_message_older_replies'),
    path('terms/', views.terms, name='terms'),
]