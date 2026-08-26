from django.db import models


class WalletResourceSync(models.Model):
    resource_id = models.CharField(max_length=255, unique=True)
    resource_type = models.CharField(max_length=32)
    payload_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    synced_at = models.DateTimeField()
