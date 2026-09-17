from django.test import TestCase
from django.urls import reverse


class ClientDemoViewTests(TestCase):
    """
    plan.md phase-9 Key Decision #3: the client demo is a real page, public
    (no staff login), making no server-side lookup of screen_key at all --
    all real work (including discovering an unreachable/unknown screen)
    happens client-side via fetch(), which this Django-view test can't
    execute (no JS test framework in this project, Phase 8 precedent). See
    Verification Plan step 9 in plan.md for the manual browser check of the
    missing-bundled-layout guard this design requires.
    """

    def test_client_demo_page_renders(self):
        response = self.client.get(reverse("client-demo", args=["mf_dashboard"]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "serving/client_demo.html")
        self.assertEqual(response.context["screen_key"], "mf_dashboard")

    def test_client_demo_accessible_without_login(self):
        """Deliberately public -- this *is* the demonstrable client, not an admin tool."""
        response = self.client.get(reverse("client-demo", args=["mf_dashboard"]))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("login", response.request["PATH_INFO"])

    def test_client_demo_unknown_screen_still_renders(self):
        """
        No DB lookup happens server-side -- even a screen_key nothing in
        this project defines renders 200. The "not found" case surfaces
        client-side as a failed aggregator fetch, exercised through the
        existing fallback chain, not a server-side 404. Intentional, not
        an oversight.
        """
        response = self.client.get(reverse("client-demo", args=["does_not_exist_screen"]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["screen_key"], "does_not_exist_screen")

    def test_client_demo_passes_through_user_id_and_force_down(self):
        response = self.client.get(
            reverse("client-demo", args=["mf_dashboard"]) + "?user_id=abc123&force_down=1"
        )

        self.assertEqual(response.context["user_id"], "abc123")
        self.assertTrue(response.context["force_down"])
