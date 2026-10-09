"""Fixed limits of the notebooks module (the configurable ones are settings)."""

from datetime import timedelta
from typing import Final

CHAT_MESSAGE_MAX_CHARS: Final = 4000
CUSTOM_PROMPT_MAX_CHARS: Final = 1000
CHAT_GOAL_MAX_CHARS: Final = 300
SEARCH_QUERY_MIN_CHARS: Final = 2
SEARCH_QUERY_MAX_CHARS: Final = 200
SEARCH_LIMIT_DEFAULT: Final = 20
SEARCH_LIMIT_MAX: Final = 100
SEARCH_HITS_PER_SOURCE: Final = 3
SEARCH_CANDIDATES_PER_HIT: Final = 10  # passages ranked per hit that is returned
SEARCH_CANDIDATES_MAX: Final = 500
STUDIO_PROMPT_MAX_CHARS: Final = 1000
NOTEBOOK_TITLE_MAX_CHARS: Final = 120
SOURCE_TITLE_MAX_CHARS: Final = 255
ARTIFACT_TITLE_MAX_CHARS: Final = 200
EMOJI_MAX_CHARS: Final = 16
PROGRESS_MAX_BYTES: Final = 16 * 1024
CONTENT_MAX_BYTES: Final = 512 * 1024
HISTORY_MESSAGES: Final = 12  # the last six turns go to the model
CHAT_LIST_LIMIT: Final = 200
PASSAGES_PAGE_DEFAULT: Final = 60
PASSAGES_PAGE_MAX: Final = 200
DELETED_RETENTION_DAYS: Final = 7
SUMMARY_DEBOUNCE_SECONDS: Final = 20
STUCK_SOURCE_MINUTES: Final = 10
STUCK_ARTIFACT_MINUTES: Final = 15
SNIPPET_CHARS: Final = 160
DEFAULT_NOTEBOOK_TITLE: Final = "Untitled notebook"
MAX_AUTO_NOTEBOOKS: Final = 120  # subject and lesson notebooks per student
AUTO_SYNC_STALE_AFTER: Final = timedelta(minutes=10)  # opening re-syncs after this
AUTO_SWEEP_AFTER: Final = timedelta(hours=1)  # the sweep re-syncs after this
AUTO_ACTIVE_WITHIN: Final = timedelta(days=30)  # the sweep skips older notebooks
AUTO_SWEEP_BATCH: Final = 200
AUTO_FANOUT_LIMIT: Final = 1000  # notebooks synced after one lesson changes
MAX_EXCLUDED_REFS: Final = 500
SHARED_DOCUMENT_GRACE_HOURS: Final = 24  # a new document may not have its source yet
SHARED_CACHE_UNUSED_DAYS: Final = 90
