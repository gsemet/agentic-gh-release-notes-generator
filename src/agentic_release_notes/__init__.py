"""Agentic, evidence-checked, user-facing release notes for any git project.

The pipeline has three layers:

1. computed evidence: release range, commits, prioritized diff, docs index, project context;
2. agent interpretation: a coding agent turns evidence into structured notes (JSON);
3. computed validation: every item must cite commits from the range and every link must
   resolve to a page and anchor of the published documentation, then a renderer produces
   the final Markdown.
"""

__version__ = "0.1.0"
