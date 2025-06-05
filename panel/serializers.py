from rest_framework import serializers
from .models import XrayUser, Server, AlertRule, Notification

class ServerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Server
        fields = '__all__'

class XrayUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = XrayUser
        fields = '__all__'

class AlertRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertRule
        fields = '__all__'

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = '__all__'
