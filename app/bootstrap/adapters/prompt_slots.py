"""The catalogue of editable prompts: every built-in system prompt part, by task.

A part shared by several tasks is registered under each, so it can be changed for
one task alone. Templates are the parts their builder fills with `str.format`.
"""

from collections.abc import Iterable

from app.bootstrap.adapters import mcp_lms_ai
from app.modules.academic.domain.schedule import subject_names
from app.modules.admission.infrastructure.ai.prompts import (
    alignment_map as admit_alignment,
)
from app.modules.admission.infrastructure.ai.prompts import goal_plan as admit_goal_plan
from app.modules.admission.infrastructure.ai.prompts import items as admit_items
from app.modules.admission.infrastructure.ai.prompts import profile_words as admit_words
from app.modules.admission.infrastructure.ai.prompts import research as admit_research
from app.modules.ai.application import transcribe_audio
from app.modules.ai.domain import prompts, prompts_author, web_prompts
from app.modules.ai.domain.prompt_registry import PromptSlot
from app.modules.notebooks.application import (
    extract_source_vision,
    gather_web_materials,
    school_knowledge,
)
from app.modules.notebooks.domain import compaction
from app.modules.notebooks.domain.assessment import blueprint, items, profile
from app.modules.notebooks.domain.exercise import feedback
from app.modules.notebooks.domain.prompts import (
    chat,
    course,
    guide,
    labels,
    slides_revise,
    studio,
)
from app.modules.posts.application import guest_assistant
from app.shared.ai_tasks import AiTask

_CHAT_TASKS = (AiTask.STUDENT_CHAT, AiTask.STUDENT_CHAT_SMART, AiTask.ADMIN_CHAT)
_STUDENT_TASKS = (AiTask.STUDENT_CHAT, AiTask.STUDENT_CHAT_SMART)
_STUDIO_TASKS = (
    AiTask.STUDIO_REPORT,
    AiTask.STUDIO_MIND_MAP,
    AiTask.STUDIO_FLASHCARDS,
    AiTask.STUDIO_QUIZ,
    AiTask.STUDIO_DATA_TABLE,
    AiTask.STUDIO_SLIDES,
    AiTask.STUDIO_INFOGRAPHIC,
    AiTask.STUDIO_EXERCISE,
)

# (tasks, name, summary, built-in text, is a template)
_PARTS: tuple[tuple[Iterable[AiTask], str, str, str, bool], ...] = (
    (
        (AiTask.ADMIT_ITEM_REVIEW,),
        "system",
        "Admission: review of an activity or honor",
        admit_items.REVIEW_SYSTEM,
        True,
    ),
    (
        (AiTask.ADMIT_ITEM_REVIEW,),
        "strict",
        "Admission: extra rule when the item text looks like an injection",
        admit_items.REVIEW_STRICT,
        False,
    ),
    (
        (AiTask.ADMIT_ITEM_INTERVIEW,),
        "system",
        "Admission: interview about an activity or honor",
        admit_items.INTERVIEW_SYSTEM,
        True,
    ),
    (
        (AiTask.ADMIT_ITEM_REWRITE_FIX,),
        "system",
        "Admission: fix of a rewrite that broke the rules",
        admit_items.REWRITE_FIX_SYSTEM,
        True,
    ),
    (
        (AiTask.ADMIT_ALIGNMENT_MAP, AiTask.ADMIT_ALIGNMENT_REFRESH),
        "system",
        "Admission: alignment of the profile with the three words",
        admit_alignment.SYSTEM,
        False,
    ),
    (
        (AiTask.ADMIT_PROFILE_WORDS,),
        "system",
        "Admission: suggestion of the three words",
        admit_words.SYSTEM,
        False,
    ),
    (
        (AiTask.ADMIT_UNIVERSITY_RESEARCH,),
        "system",
        "Admission: summary of one university",
        admit_research.SYSTEM,
        False,
    ),
    (
        (AiTask.ADMIT_GOAL_PLAN,),
        "system",
        "Admission: milestone suggestions for the goal plan",
        admit_goal_plan.SYSTEM,
        False,
    ),
    (
        _CHAT_TASKS,
        "data_rules",
        "How the assistant treats data",
        prompts._DATA_RULES,
        False,
    ),
    (_CHAT_TASKS, "safety_rules", "Safety rules", prompts._SAFETY_RULES, False),
    (_CHAT_TASKS, "format_rules", "Answer format", prompts._FORMAT_RULES, True),
    (_CHAT_TASKS, "priorities", "Priorities", prompts.PRIORITIES, False),
    (_CHAT_TASKS, "answer_now", "Answer without more tools", prompts.ANSWER_NOW, False),
    (_CHAT_TASKS, "tool_policy", "Tool use", prompts._TOOL_POLICY, True),
    (_CHAT_TASKS, "telegram_rules", "Telegram replies", prompts.TELEGRAM_RULES, False),
    (
        _STUDENT_TASKS,
        "student_role",
        "Student assistant role",
        prompts._STUDENT_ROLE,
        False,
    ),
    (
        (AiTask.ADMIN_CHAT,),
        "admin_role",
        "Staff assistant role",
        prompts._ADMIN_ROLE,
        False,
    ),
    (
        (AiTask.LMS_AUTHORING,),
        "author",
        "Course author",
        prompts_author._AUTHOR_PROMPT,
        True,
    ),
    (
        (AiTask.LMS_AUTHORING,),
        "mcp_system",
        "Course tools (MCP)",
        mcp_lms_ai._SYSTEM,
        False,
    ),
    (
        (AiTask.LMS_AUTHORING,),
        "course",
        "Course from a notebook",
        course._COURSE_SYSTEM,
        True,
    ),
    (
        (AiTask.CHAT_SUMMARY,),
        "system",
        "Chat history summary",
        prompts.SUMMARY_SYSTEM_PROMPT,
        False,
    ),
    (
        (AiTask.WEB_SEARCH, AiTask.DISCOVER),
        "plan",
        "Search queries",
        web_prompts.PLAN_SYSTEM,
        False,
    ),
    (
        (AiTask.WEB_SEARCH, AiTask.DISCOVER),
        "rank",
        "Result ranking",
        web_prompts.RANK_SYSTEM,
        False,
    ),
    (
        (AiTask.VOICE_TRANSCRIBE,),
        "system",
        "Voice transcription",
        transcribe_audio.SYSTEM,
        False,
    ),
    (
        (AiTask.SOURCE_VISION_EXTRACT,),
        "system",
        "Scanned page reading",
        extract_source_vision.SYSTEM,
        False,
    ),
    (
        (AiTask.WEB_MATERIAL_TRIAGE,),
        "system",
        "Web material triage",
        gather_web_materials.TRIAGE_SYSTEM,
        False,
    ),
    (
        (AiTask.MEDIA_DESCRIBE,),
        "describe",
        "Image description",
        gather_web_materials.DESCRIBE_SYSTEM,
        False,
    ),
    (
        (AiTask.MEDIA_DESCRIBE,),
        "transcribe",
        "Media transcription",
        gather_web_materials.TRANSCRIBE_SYSTEM,
        False,
    ),
    (
        (AiTask.NOTEBOOK_CHAT,),
        "school_knowledge",
        "School knowledge answers",
        school_knowledge._SYSTEM,
        False,
    ),
    (
        (AiTask.NOTEBOOK_CHAT,),
        "student_intro",
        "Notebook assistant intro",
        chat._STUDENT_INTRO,
        False,
    ),
    (
        (AiTask.NOTEBOOK_CHAT,),
        "course_intro",
        "Course assistant intro",
        chat._COURSE_INTRO,
        False,
    ),
    (
        (AiTask.NOTEBOOK_CHAT,),
        "course_rules",
        "Course assistant rules",
        chat._COURSE_RULES,
        False,
    ),
    ((AiTask.SOURCE_GUIDE,), "guide", "Source guide", guide._GUIDE, True),
    ((AiTask.NOTEBOOK_SUMMARY,), "summary", "Notebook summary", guide._SUMMARY, True),
    ((AiTask.SOURCE_LABELS,), "labels", "Source labels", labels._LABELS, True),
    (_STUDIO_TASKS, "studio", "Studio artifact", studio._SYSTEM, True),
    (
        (AiTask.STUDIO_SLIDES_REVISE,),
        "revision",
        "Slide revision",
        slides_revise._REVISION,
        True,
    ),
    (
        (AiTask.STUDIO_ASSESSMENT_PLAN,),
        "system",
        "Assessment plan",
        blueprint.PLAN_SYSTEM,
        False,
    ),
    ((AiTask.STUDIO_ITEM_VERIFY,), "system", "Item check", items.VERIFY_SYSTEM, False),
    (
        (AiTask.STUDIO_SOURCE_PROFILE,),
        "system",
        "Source profile",
        profile.PROFILE_SYSTEM,
        False,
    ),
    (
        (AiTask.CONTEXT_COMPACT,),
        "system",
        "Context compaction",
        compaction.COMPACT_SYSTEM_PROMPT,
        False,
    ),
    (
        (AiTask.EXERCISE_FEEDBACK,),
        "system",
        "Exercise feedback",
        feedback.SYSTEM,
        False,
    ),
    (
        (AiTask.SUBJECT_TRANSLATE,),
        "system",
        "Subject names",
        subject_names.SYSTEM_PROMPT,
        False,
    ),
    ((AiTask.GUEST_CHAT,), "system", "Guest assistant", guest_assistant.SYSTEM, False),
)


def prompt_slots() -> list[PromptSlot]:
    """Every editable prompt slot."""
    return [
        PromptSlot(
            task=task.value, name=name, summary=summary, builtin=text, template=template
        )
        for tasks, name, summary, text, template in _PARTS
        for task in tasks
    ]
