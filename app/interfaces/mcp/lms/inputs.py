"""Argument models of the LMS Course server (shown to AI clients as JSON schema).

The models live in ``app.shared.contracts.lms_blocks``; the course author assistant
uses the same ones.
"""

from app.shared.contracts.lms_blocks import (
    OptionInput,
    QuestionInput,
    QuestionList,
    QuizSettingsInput,
)

__all__ = ["OptionInput", "QuestionInput", "QuestionList", "QuizSettingsInput"]
