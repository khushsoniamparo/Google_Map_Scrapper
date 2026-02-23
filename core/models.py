from django.db import models
from django.contrib.auth.models import User

class Subscription(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='subscription')
    is_premium = models.BooleanField(default=False)
    plan_name = models.CharField(max_length=100, default='Free')
    premium_searches = models.IntegerField(default=10)
    razorpay_order_id = models.CharField(max_length=200, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=200, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=200, blank=True, null=True)
    expiry_date = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.plan_name}"
