from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

router = DefaultRouter()
router.register('categories', views.CategoryViewSet, basename='category')
router.register('products', views.ProductViewSet, basename='product')
router.register('orders', views.OrderViewSet, basename='order')
router.register('notifications', views.NotificationViewSet, basename='notification')
router.register('users', views.UserManagementViewSet, basename='user-management')

urlpatterns = [
    path('auth/login/', views.LoginView.as_view(), name='api_login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='api_token_refresh'),
    path('auth/register/', views.RegisterView.as_view(), name='api_register'),
    path('auth/verify-otp/', views.VerifyOTPView.as_view(), name='api_verify_otp'),
    path('auth/me/', views.MeView.as_view(), name='api_me'),
    path('', include(router.urls)),
]