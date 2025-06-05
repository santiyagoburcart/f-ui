from rest_framework import viewsets
from .models import Server, XrayUser, AlertRule, Notification
from .serializers import ServerSerializer, XrayUserSerializer, AlertRuleSerializer, NotificationSerializer

class ServerViewSet(viewsets.ModelViewSet):
    queryset = Server.objects.all()
    serializer_class = ServerSerializer

class XrayUserViewSet(viewsets.ModelViewSet):
    queryset = XrayUser.objects.all()
    serializer_class = XrayUserSerializer

class AlertRuleViewSet(viewsets.ModelViewSet):
    queryset = AlertRule.objects.all()
    serializer_class = AlertRuleSerializer

class NotificationViewSet(viewsets.ModelViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
