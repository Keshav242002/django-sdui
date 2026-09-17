from django.core.exceptions import ValidationError
from django.db import models

BADGE_TEXT_MAX_LENGTH = 24


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

    def clean(self):
        """
        Validate the optional `badge_text` content field inside `config`.

        Deliberately content-only, not visual: coloring/theming is not
        server-configurable (Phase 8 revision -- brand theme is owned by
        the client's fixed design system, matching how production SDUI
        systems at this scale actually split the concern; only the admin
        preview tool applies any color, and that's hardcoded per widget
        type in preview_renderer.js, never read from Section.config). This
        field is just a short label (e.g. "NEW") the client renders as-is.

        Only fires through ModelForm.full_clean() -- i.e. the Django Admin,
        the only path that writes Section rows in this project today. Direct
        ORM writes (a future management command/migration touching
        Section.config) bypass this -- a documented gap, not a guarantee.
        """
        super().clean()
        badge_text = (self.config or {}).get("badge_text")
        if badge_text is not None and len(str(badge_text)) > BADGE_TEXT_MAX_LENGTH:
            raise ValidationError(
                {"config": f"badge_text must be {BADGE_TEXT_MAX_LENGTH} characters or fewer."}
            )


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
            ),
            models.UniqueConstraint(
                fields=["screen"],
                condition=models.Q(is_current=True),
                name="unique_current_layout_version_per_screen",
            ),
        ]

    def __str__(self):
        return f"{self.screen.key} v{self.version_number}"

    def save(self, *args, **kwargs):
        """
        Enforce the invariant that only one LayoutVersion per screen can be
        is_current=True. Backed by a DB-level partial unique index
        (Meta.constraints: unique_current_layout_version_per_screen,
        plan.md phase-9) as a safety net -- this application-level guard
        remains the primary enforcement path since it also handles the
        "unset the previous one" transition the DB constraint alone can't.
        """
        if self.is_current:
            LayoutVersion.objects.filter(screen=self.screen, is_current=True).exclude(
                pk=self.pk
            ).update(is_current=False)
        super().save(*args, **kwargs)
