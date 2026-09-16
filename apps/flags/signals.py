import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.common.cache import cache_client, flag_cache_key
from apps.flags.models import FeatureFlag

logger = logging.getLogger(__name__)


@receiver(post_save, sender=FeatureFlag)
def invalidate_flag_cache(sender, instance, **kwargs):
    cache_client.delete(flag_cache_key(instance.key))
    logger.info("Invalidated cache for flag '%s'", instance.key)
