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
