"""Students tools of flash cards, tests, notebooks, library and knowledge."""

from types import ModuleType

from app.interfaces.mcp.student.tools import (
    add_notebook_sources,
    batch_edit_flashcards,
    batch_edit_test_questions,
    create_notebook,
    create_test,
    delete_flashcards,
    generate_notebook_output,
    get_library_item,
    get_notebook,
    get_test,
    list_notebook_outputs,
    list_notebooks,
    list_tests,
    read_library_text,
    read_notebook_source,
    search_knowledge,
    search_library,
    search_notebooks,
    update_flashcard_set,
)

TOOL_MODULES: tuple[ModuleType, ...] = (
    update_flashcard_set,
    batch_edit_flashcards,
    delete_flashcards,
    create_test,
    get_test,
    list_tests,
    batch_edit_test_questions,
    search_knowledge,
    list_notebooks,
    get_notebook,
    search_notebooks,
    read_notebook_source,
    list_notebook_outputs,
    create_notebook,
    add_notebook_sources,
    generate_notebook_output,
    search_library,
    get_library_item,
    read_library_text,
)
