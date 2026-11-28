"""Deterministic fake document for the admission project ideas."""

from typing import Any

PROJECTS_SCHEMA = "project_ideas"

_IDEAS: tuple[tuple[str, str, str, str, str, int, list[str]], ...] = (
    (
        "olympiad-task-bank",
        "Olympiad task bank for grade 9 chemistry",
        "Grade 9 students of your lyceum prepare for the olympiad from scattered "
        "photos of old tasks. You collect the tasks of the last five years, sort "
        "them by topic and add short solutions.",
        "A shared folder with 150 sorted tasks and solutions.",
        "30 students open it at least twice in a month.",
        6,
        ["org_outreach"],
    ),
    (
        "canteen-queue-study",
        "Canteen queue study with a fix",
        "The lunch queue takes half of the break. You time it for two weeks, find "
        "the slow point and test one change together with the canteen staff.",
        "A two-page note with your measurements and the tested change.",
        "The average wait falls by 3 minutes.",
        4,
        ["pitching"],
    ),
    (
        "timetable-bot",
        "Timetable reminder bot for your class",
        "Classmates miss room changes posted late in the evening. You build a bot "
        "that sends tomorrow's lessons and changes to the class chat.",
        "A working bot used by your class every school day.",
        "20 classmates keep it switched on for a month.",
        5,
        ["website_tech", "product_dev"],
    ),
    (
        "air-quality-log",
        "Air quality log for three classrooms",
        "Nobody knows how stuffy the classrooms get by the fourth lesson. You "
        "measure the air in three rooms for a month and show when to open windows.",
        "A dataset of one month and a one-page guide for teachers.",
        "Three teachers follow the airing times for two weeks.",
        8,
        ["product_dev", "fundraising"],
    ),
    (
        "reading-hour",
        "Weekly English reading hour for grade 5",
        "Grade 5 pupils of the school next door rarely read English aloud. You run "
        "a weekly reading hour with two classmates and track new words.",
        "Eight sessions held, with attendance and word lists.",
        "12 pupils come to at least six of the eight sessions.",
        8,
        ["org_outreach"],
    ),
    (
        "open-source-translation",
        "Uzbek translation of an open learning tool",
        "A free tool for learning to code has no Uzbek version. You translate its "
        "first lessons and send them to the authors.",
        "A translation of ten lessons accepted by the project.",
        "Ten lessons accepted and 15 schoolmates finish the first one.",
        4,
        [],
    ),
)


def build_project_ideas_document(schema_name: str) -> dict[str, Any] | None:
    """Return a schema-valid list of 6 concrete projects, else None."""
    if schema_name != PROJECTS_SCHEMA:
        return None
    return {
        "projects": [
            {
                "key": key,
                "title": title,
                "summary": summary,
                "analogs": [],
                "challenges": [
                    "Finding time every week: fix two evenings in your calendar",
                    "Getting the first users: start with five people you know",
                ],
                "application_effect": "Gives a result with numbers you can describe "
                "in an essay and an activity entry, and shows that you finish things.",
                "first_steps": [
                    "Write in one sentence who it is for and what changes for them",
                    "Ask three of those people how they cope today",
                    "Make the smallest version and show it to them",
                ],
                "help_tags": tags,
                "why_you": "It uses what you already know and the people around you.",
                "deliverable": deliverable,
                "measure": measure,
                "weeks": weeks,
            }
            for key, title, summary, deliverable, measure, weeks, tags in _IDEAS
        ]
    }
