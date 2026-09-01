"""Canonical field vocabularies and the value shapes each field expects.

This file is the reason column mapping rarely needs a model. Most QA workbooks
name their columns from a small, stable pool of phrasings; matching against that
pool resolves the overwhelming majority of columns deterministically and leaves
only genuine oddities for the tie-breaker.

`expects` is the second half of the mechanism. A header can say one thing while
the column holds another — a broken dropdown, a repurposed column — and matching
on the name alone would accept it. Declaring the expected value shape lets the
mapper catch that disagreement instead of propagating it.
"""

from __future__ import annotations

from enum import Enum


class ValueShape(str, Enum):
    IDENTIFIER = "identifier"   # short, mostly unique
    DATE = "date"
    ENUM = "enum"               # few distinct short values
    TEXT = "text"               # prose, often long
    ANY = "any"


# field -> (synonyms, expected value shape)
BUG_FIELDS: dict[str, tuple[tuple[str, ...], ValueShape]] = {
    "id": (
        ("issue no", "issue number", "bug id", "bug no", "id", "ticket",
         "ticket id", "defect id", "issue id", "key", "#"),
        ValueShape.IDENTIFIER,
    ),
    "created": (
        ("created", "created on", "date", "date created", "reported on",
         "raised on", "opened", "logged"),
        ValueShape.DATE,
    ),
    "severity": (
        ("severity", "priority", "impact", "criticality"),
        ValueShape.ENUM,
    ),
    "issue_type": (
        ("issue type", "type", "category", "bug type", "defect type", "area"),
        ValueShape.ENUM,
    ),
    "summary": (
        ("summary", "title", "short description", "headline", "issue"),
        ValueShape.TEXT,
    ),
    "description": (
        ("description", "details", "detail", "long description", "notes"),
        ValueShape.TEXT,
    ),
    "steps": (
        ("steps", "steps to reproduce", "repro steps", "reproduction steps",
         "how to reproduce"),
        ValueShape.TEXT,
    ),
    "actual": (
        ("actual result", "actual", "actual behaviour", "actual behavior",
         "observed", "observed result"),
        ValueShape.TEXT,
    ),
    "expected": (
        ("expected result", "expected", "expected behaviour",
         "expected behavior", "should be"),
        ValueShape.TEXT,
    ),
    "build": (
        ("build", "build & version", "build and version", "version",
         "build version", "found in build", "release"),
        ValueShape.ENUM,
    ),
    "status": (
        ("status", "state", "issue status", "current status"),
        ValueShape.ENUM,
    ),
    "resolution": (
        ("resolution", "resolved as", "outcome", "disposition"),
        ValueShape.ENUM,
    ),
    "dev_resolution": (
        ("dev resolution", "developer resolution", "dev outcome"),
        ValueShape.ANY,
    ),
    "dev_comments": (
        ("dev comments", "developer comments", "dev notes", "dev feedback",
         "developer notes"),
        ValueShape.TEXT,
    ),
    "comments": (
        ("comments", "comment", "qa comments", "remarks", "notes"),
        ValueShape.TEXT,
    ),
    "repro_rate": (
        ("repro rate", "reproduction rate", "frequency", "reproducibility"),
        ValueShape.ENUM,
    ),
    "attachments": (
        ("attachments", "attachment", "screenshot", "screenshots", "evidence",
         "link", "links"),
        ValueShape.ANY,
    ),
}

TEST_FIELDS: dict[str, tuple[tuple[str, ...], ValueShape]] = {
    # A real test case id, when the source has one. Preferred over the sheet
    # row as the case's reference everywhere downstream — "TC-001" is what a
    # tester will search for, "TC-14" (a row number) is not.
    "case_id": (
        ("test case id", "testcase id", "tc id", "case id", "test id",
         "test case no", "tc no", "id"),
        ValueShape.IDENTIFIER,
    ),
    "module": (
        ("module", "feature", "component", "area", "suite", "epic"),
        ValueShape.ENUM,
    ),
    # A short name for the case, distinct from its long description. Sheets
    # commonly carry one or the other; some carry both.
    "title": (
        ("title", "test case title", "name", "test name", "summary"),
        ValueShape.TEXT,
    ),
    # Test plans routinely prioritise cases (Core/High/Medium/Low). Without
    # this the column falls through to the bug vocabulary and gets read as a
    # severity, which is how a test plan ends up rendered as a bug tracker.
    "priority": (
        ("priority", "test priority", "criticality", "importance", "tier"),
        ValueShape.ENUM,
    ),
    "preconditions": (
        ("preconditions", "precondition", "pre requisites", "prerequisites",
         "setup", "given"),
        ValueShape.TEXT,
    ),
    "description": (
        ("test case description", "test case", "description", "test",
         "scenario", "test scenario", "case", "test description"),
        ValueShape.TEXT,
    ),
    "steps": (
        ("verification steps", "steps", "test steps", "procedure",
         "how to test"),
        ValueShape.TEXT,
    ),
    "expected": (
        ("expected result", "expected results", "expected", "expected outcome",
         "final expected result", "acceptance criteria"),
        ValueShape.TEXT,
    ),
    "status": (
        ("status", "result", "test result", "outcome", "state", "pass fail",
         "execution status"),
        ValueShape.ENUM,
    ),
    "linked_bug_ids": (
        ("bug id", "bug", "issue no", "issue id", "defect", "linked bug",
         "related bug", "bug ref"),
        ValueShape.IDENTIFIER,
    ),
    "comments": (
        ("comments", "comment", "remarks", "notes"),
        ValueShape.TEXT,
    ),
}

MATRIX_FIELDS: dict[str, tuple[tuple[str, ...], ValueShape]] = {
    "item": (
        ("item", "string", "key", "label", "element", "entry", "text",
         "localization", "term"),
        ValueShape.TEXT,
    ),
    "comment": (
        ("comment", "comments", "notes", "remarks"),
        ValueShape.TEXT,
    ),
}


# Enum vocabularies used both for canonicalization and to recognise a column by
# its values when its header is unhelpful.
SEVERITY_TERMS = {
    "blocker": "Blocker", "block": "Blocker", "showstopper": "Blocker",
    "critical": "Critical", "crit": "Critical",
    "major": "Major", "high": "Major",
    "minor": "Minor", "medium": "Minor", "low": "Minor", "moderate": "Minor",
    "trivial": "Trivial", "cosmetic": "Trivial", "nit": "Trivial",
    # P-levels, as issue trackers usually write them. Included because the
    # ordering is what severity is for, and leaving these unmapped would send
    # a whole tracker's worth of bugs to Unknown — rank 0, sorted last, which
    # is the opposite of where a P1 belongs.
    "p1": "Blocker", "p2": "Critical", "p3": "Major", "p4": "Minor",
    "s1": "Blocker", "s2": "Critical", "s3": "Major", "s4": "Minor",
}

BUG_STATUS_TERMS = {
    "open": "Open", "new": "Open", "reopened": "Open", "to do": "Open",
    "in progress": "In Progress", "in-progress": "In Progress",
    "wip": "In Progress", "active": "In Progress", "assigned": "In Progress",
    "qa ready": "QA Ready", "ready for qa": "QA Ready", "fixed": "QA Ready",
    "resolved": "QA Ready", "ready for test": "QA Ready",
    "closed": "Closed", "done": "Closed", "verified": "Closed",
    "complete": "Closed", "completed": "Closed",
    "deferred": "Deferred", "backlog": "Deferred", "wont fix": "Deferred",
    "won't fix": "Deferred", "postponed": "Deferred",
}

RESULT_TERMS = {
    "pass": "Pass", "passed": "Pass", "ok": "Pass", "success": "Pass",
    "fail": "Fail", "failed": "Fail", "failure": "Fail",
    "some issue": "Some Issue", "partial": "Some Issue",
    "issues": "Some Issue", "minor issue": "Some Issue",
    "blocked": "Blocked", "block": "Blocked",
    "in progress": "In Progress", "wip": "In Progress", "ongoing": "In Progress",
    "not run": "Not Run", "not tested": "Not Run", "pending": "Not Run",
    "n/a": "Not Run", "na": "Not Run", "-": "Not Run",
}

FIELD_SETS = {
    "bugs": BUG_FIELDS,
    "test_cases": TEST_FIELDS,
    "matrix_results": MATRIX_FIELDS,
}
