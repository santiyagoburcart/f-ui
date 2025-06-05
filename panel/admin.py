from django.contrib import admin
from .models import Server, XrayUser, AlertRule, Notification

# Register your models here.
admin.site.register(Server)
admin.site.register(XrayUser)
admin.site.register(AlertRule)
admin.site.register(Notification)
