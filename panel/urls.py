from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ServerViewSet, XrayUserViewSet, AlertRuleViewSet, NotificationViewSet

router = DefaultRouter()
router.register(r'servers', ServerViewSet)
router.register(r'xrayusers', XrayUserViewSet)
router.register(r'alertrules', AlertRuleViewSet)
router.register(r'notifications', NotificationViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
