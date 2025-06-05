import uuid
from django.db import models
from django.contrib.auth.models import User # این ایمپورت فعلا استفاده نمی‌شود اما برای آینده ممکن است لازم باشد

class Server(models.Model):
    name = models.CharField(max_length=100, unique=True)
    address = models.CharField(max_length=255) # Can be IP or domain
    port = models.IntegerField() # Xray server API/gRPC port
    api_token = models.CharField(max_length=255, blank=True, null=True) # For security, can be blank/null if not all servers require a token
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class XrayUser(models.Model):
    server = models.ForeignKey(Server, on_delete=models.CASCADE)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    email = models.CharField(max_length=255, unique=True) # For user identification, can be unique if emails must be unique across one server or the entire system
    protocol = models.CharField(max_length=50) # e.g., VLESS, VMess, Trojan
    uplink_bytes = models.BigIntegerField(default=0) # Uploaded traffic in bytes
    downlink_bytes = models.BigIntegerField(default=0) # Downloaded traffic in bytes
    total_bytes = models.BigIntegerField(default=0) # Total allowed traffic in bytes (0 or negative for unlimited)
    expiry_time = models.DateTimeField(null=True, blank=True) # Expiry date (null/blank for no expiration)
    enable = models.BooleanField(default=True) # Active/inactive status
    settings_json = models.JSONField(null=True, blank=True) # For storing protocol-specific settings
    last_online_time = models.DateTimeField(null=True, blank=True) # Last online time
    is_online = models.BooleanField(default=False) # Real-time online status
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.email

class AlertRule(models.Model):
    name = models.CharField(max_length=100, unique=True)

    ALERT_TYPE_CHOICES = [
        ('inactive_user', 'Inactive User'),
        ('low_traffic_remaining', 'Low Traffic Remaining'),
    ]
    alert_type = models.CharField(max_length=50, choices=ALERT_TYPE_CHOICES)

    threshold_days_inactive = models.IntegerField(null=True, blank=True) # Number of inactive days (for inactive_user alert)
    threshold_gb_remaining = models.FloatField(null=True, blank=True) # Minimum remaining traffic in GB (for low_traffic_remaining alert)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class Notification(models.Model):
    xray_user = models.ForeignKey(XrayUser, on_delete=models.CASCADE)
    alert_rule = models.ForeignKey(AlertRule, on_delete=models.SET_NULL, null=True, blank=True) # If the rule is deleted, the notification remains but without a specific rule
    message = models.TextField() # Alert message
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification for {self.xray_user.email} - Rule: {self.alert_rule.name if self.alert_rule else 'N/A'}"
