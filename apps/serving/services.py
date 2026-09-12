"""
The screen-aggregation service.

Empty shell for Phase 1. Phase 2 will add the aggregator that assembles a
Screen's active Sections, calls each widget's owning-app service function to
fetch its data (per-section error isolation — see rules.md §3), and returns
the assembled screen response.
"""
