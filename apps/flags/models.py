from django.db import models


class FeatureFlag(models.Model):
    key = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    is_enabled = models.BooleanField(default=False)
    rollout_percentage = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rollout_percentage__gte=0)
                & models.Q(rollout_percentage__lte=100),
                name="rollout_percentage_between_0_and_100",
            )
        ]

    def __str__(self):
        return self.key


class TargetingRule(models.Model):
    class Operator(models.TextChoices):
        EQUALS = "equals", "Equals"
        IN = "in", "In"
        GTE = "gte", "Greater than or equal"
        LTE = "lte", "Less than or equal"
        CONTAINS = "contains", "Contains"

    feature_flag = models.ForeignKey(
        FeatureFlag, on_delete=models.CASCADE, related_name="targeting_rules"
    )
    attribute = models.CharField(max_length=100)
    operator = models.CharField(max_length=20, choices=Operator.choices)
    value = models.JSONField()

    def __str__(self):
        return f"{self.feature_flag.key}: {self.attribute} {self.operator} {self.value}"
