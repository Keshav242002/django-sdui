from django.test import TestCase

from apps.serving.services import _compare_versions


class CompareVersionsTests(TestCase):
    def test_equal_versions(self):
        self.assertTrue(_compare_versions("2.0.0", "2.0.0"))

    def test_client_below_minimum(self):
        self.assertFalse(_compare_versions("1.9.9", "2.0.0"))

    def test_short_client_version_padded(self):
        self.assertTrue(_compare_versions("2.0", "2.0.0"))

    def test_asymmetric_padding(self):
        self.assertTrue(_compare_versions("2", "1.5"))

    def test_empty_client_version_with_minimum_set(self):
        self.assertFalse(_compare_versions("", "1.0.0"))

    def test_no_minimum_always_shown(self):
        self.assertTrue(_compare_versions("", ""))
        self.assertTrue(_compare_versions("1.0.0", ""))
