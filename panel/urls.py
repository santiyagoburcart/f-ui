from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ServerViewSet,
    XrayUserViewSet,
    AlertRuleViewSet,
    NotificationViewSet,
    UserTrafficStatsView, # New import
    UserOnlineStatusView  # New import
)

router = DefaultRouter()
router.register(r'servers', ServerViewSet)
router.register(r'xrayusers', XrayUserViewSet)
router.register(r'alertrules', AlertRuleViewSet)
router.register(r'notifications', NotificationViewSet)

urlpatterns = [
    path('', include(router.urls)),
    # URLs for XrayUser specific stats
    path('xrayusers/<int:user_pk>/traffic/', UserTrafficStatsView.as_view(), name='xrayuser-traffic-stats'),
    path('xrayusers/<int:user_pk>/online-status/', UserOnlineStatusView.as_view(), name='xrayuser-online-status'),
]
