"""
Business logic for the screens app.
"""

from apps.common.exceptions import LayoutNotPublished
from apps.screens.models import Screen


def get_active_sections(screen_key: str):
    """
    Return the ordered, active Sections for a screen.

    Phase 3 will swap this to read a published LayoutVersion snapshot from
    Redis instead of live Section rows -- this is the one call site that
    changes; the serving app's assemble_screen() and its tests are
    unaffected by that swap.
    """
    try:
        screen = Screen.objects.get(key=screen_key)
    except Screen.DoesNotExist:
        raise LayoutNotPublished(f"No screen found for key '{screen_key}'.")

    sections = list(
        screen.sections.filter(is_active=True).select_related("widget_type").order_by("order")
    )
    if not sections:
        raise LayoutNotPublished(f"Screen '{screen_key}' has no active sections.")
    return sections
