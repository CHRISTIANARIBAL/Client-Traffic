
from django.db import models
from django.contrib.auth.models import User


class CustomerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    pppoe_username = models.CharField(max_length=255, unique=True)
    customer_name = models.CharField(max_length=255)

    def __str__(self):
        return self.user.username


class TrafficHistory(models.Model):
    customer = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name="traffic_history",
    )
    pppoe_username = models.CharField(max_length=255, db_index=True)
    ac = models.CharField(max_length=50)
    upload = models.BigIntegerField()
    download = models.BigIntegerField()
    timestamp = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["timestamp"]
        indexes = [
            models.Index(
                fields=["customer", "timestamp"],
                name="traffic_cust_time_idx",
            ),
        ]

    def __str__(self):
        return f"{self.pppoe_username} - {self.timestamp}"
