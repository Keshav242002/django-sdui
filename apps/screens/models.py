from django.db import models


class Screen(models.Model):
    """A top-level SDUI screen, e.g. `mf_dashboard`, `fund_detail`."""

    key = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key


class WidgetType(models.Model):
    """A widget registered in the client's widget registry."""

    key = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    schema = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.key


class Section(models.Model):
    """A single widget instance placed on a Screen."""

    screen = models.ForeignKey(Screen, on_delete=models.CASCADE, related_name="sections")
    widget_type = models.ForeignKey(WidgetType, on_delete=models.PROTECT, related_name="sections")
    title = models.CharField(max_length=200, blank=True, default="")
    order = models.PositiveIntegerField()
    config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    min_app_version = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.screen.key} / {self.widget_type.key} ({self.order})"


class LayoutVersion(models.Model):
    """An immutable, published snapshot of a Screen's sections."""

    screen = models.ForeignKey(Screen, on_delete=models.CASCADE, related_name="layout_versions")
    version_number = models.PositiveIntegerField()
    sections_snapshot = models.JSONField(default=list)
    published_at = models.DateTimeField(auto_now_add=True)
    published_by = models.CharField(max_length=150, blank=True, default="")
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["screen", "version_number"], name="unique_screen_version_number"
            )
        ]

    def __str__(self):
        return f"{self.screen.key} v{self.version_number}"

    def save(self, *args, **kwargs):
        """
        Enforce the invariant that only one LayoutVersion per screen can be
        is_current=True. DB-level partial unique index is deferred to Phase 3.
        """
        if self.is_current:
            LayoutVersion.objects.filter(screen=self.screen, is_current=True).exclude(
                pk=self.pk
            ).update(is_current=False)
        super().save(*args, **kwargs)
