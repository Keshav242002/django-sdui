from django.test import TestCase

from apps.flags.models import FeatureFlag, TargetingRule


class FeatureFlagModelTests(TestCase):
    def test_created_with_rollout_percentage(self):
        flag = FeatureFlag.objects.create(
            key="new_recommended_funds_widget",
            description="Enables the new recommended funds widget",
            is_enabled=True,
            rollout_percentage=25,
        )
        self.assertEqual(flag.rollout_percentage, 25)
        self.assertTrue(flag.is_enabled)


class TargetingRuleModelTests(TestCase):
    def test_deleting_flag_cascades_to_rules(self):
        flag = FeatureFlag.objects.create(key="new_widget", rollout_percentage=50)
        TargetingRule.objects.create(
            feature_flag=flag, attribute="app_version", operator="gte", value="5.0.0"
        )

        self.assertEqual(TargetingRule.objects.count(), 1)
        flag.delete()
        self.assertEqual(TargetingRule.objects.count(), 0)
