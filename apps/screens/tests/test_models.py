from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from apps.screens.models import LayoutVersion, Screen, Section, WidgetType


class ScreenModelTests(TestCase):
    def test_key_uniqueness_enforced(self):
        Screen.objects.create(key="mf_dashboard", name="MF Dashboard")
        with self.assertRaises(IntegrityError):
            Screen.objects.create(key="mf_dashboard", name="Duplicate")


class SectionModelTests(TestCase):
    def test_sections_ordered_by_order_field(self):
        screen = Screen.objects.create(key="mf_dashboard", name="MF Dashboard")
        widget_type = WidgetType.objects.create(key="grid", name="Grid")
        Section.objects.create(screen=screen, widget_type=widget_type, order=3)
        Section.objects.create(screen=screen, widget_type=widget_type, order=1)
        Section.objects.create(screen=screen, widget_type=widget_type, order=2)

        orders = list(screen.sections.values_list("order", flat=True))
        self.assertEqual(orders, [1, 2, 3])


class SectionBadgeTextValidationTests(TestCase):
    """
    Section.clean() validates the optional config.badge_text content
    field. No color/theming validation here -- coloring is not
    server-configurable (Phase 8 revision, see models.py::Section.clean()
    docstring); only badge_text (a short label) is admin-authored data.
    clean() is invoked directly (not full_clean()), exercising exactly
    the method the Admin's ModelForm calls.
    """

    def setUp(self):
        self.screen = Screen.objects.create(key="mf_dashboard", name="MF Dashboard")
        self.widget_type = WidgetType.objects.create(key="grid", name="Grid")

    def _section(self, badge_text):
        return Section(
            screen=self.screen,
            widget_type=self.widget_type,
            order=1,
            config={"badge_text": badge_text},
        )

    def test_rejects_badge_text_over_max_length(self):
        section = self._section("x" * 25)
        with self.assertRaises(ValidationError):
            section.clean()

    def test_accepts_badge_text_at_max_length(self):
        section = self._section("x" * 24)
        section.clean()  # does not raise

    def test_no_badge_text_is_valid(self):
        section = Section(screen=self.screen, widget_type=self.widget_type, order=1, config={})
        section.clean()  # does not raise


class LayoutVersionModelTests(TestCase):
    def test_setting_is_current_unsets_previous_version(self):
        screen = Screen.objects.create(key="mf_dashboard", name="MF Dashboard")
        v1 = LayoutVersion.objects.create(
            screen=screen, version_number=1, sections_snapshot=[], is_current=True
        )
        v2 = LayoutVersion.objects.create(
            screen=screen, version_number=2, sections_snapshot=[], is_current=True
        )

        v1.refresh_from_db()
        v2.refresh_from_db()
        self.assertFalse(v1.is_current)
        self.assertTrue(v2.is_current)

    def test_layoutversion_db_constraint_rejects_second_current_row(self):
        """
        plan.md phase-9: unique_current_layout_version_per_screen is a
        DB-level safety net behind save()'s application-level guard
        (test above). QuerySet.update() bypasses save() entirely (a raw
        SQL UPDATE), so it's the only way to actually exercise the
        constraint itself rather than just re-proving save()'s Python
        logic.
        """
        screen = Screen.objects.create(key="mf_dashboard", name="MF Dashboard")
        LayoutVersion.objects.create(
            screen=screen, version_number=1, sections_snapshot=[], is_current=True
        )
        v2 = LayoutVersion.objects.create(
            screen=screen, version_number=2, sections_snapshot=[], is_current=False
        )

        with self.assertRaises(IntegrityError):
            LayoutVersion.objects.filter(pk=v2.pk).update(is_current=True)
