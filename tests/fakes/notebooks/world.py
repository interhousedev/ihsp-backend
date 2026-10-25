"""The other modules as fakes, bundled for the notebook tests."""

from dataclasses import dataclass, field

from tests.fakes.notebooks.ai import FakeChats
from tests.fakes.notebooks.classwork import FakeClasswork, FakeTermCalendar
from tests.fakes.notebooks.fetcher import FakeWebFetcher
from tests.fakes.notebooks.files import FakeNotebookFiles
from tests.fakes.notebooks.flashcards import FakeFlashcardSets
from tests.fakes.notebooks.library import FakeLibrarySourceReader
from tests.fakes.notebooks.links import FakeLessonLinks
from tests.fakes.notebooks.lms import FakeLms
from tests.fakes.notebooks.schedule import FakeLessonSchedule
from tests.fakes.notebooks.transcripts import FakeTranscriptProvider


@dataclass(slots=True)
class World:
    """The other modules, as fakes the tests fill and inspect."""

    files: FakeNotebookFiles = field(default_factory=FakeNotebookFiles)
    chats: FakeChats = field(default_factory=FakeChats)
    links: FakeLessonLinks = field(default_factory=FakeLessonLinks)
    schedule: FakeLessonSchedule = field(default_factory=FakeLessonSchedule)
    flashcards: FakeFlashcardSets = field(default_factory=FakeFlashcardSets)
    lms: FakeLms = field(default_factory=FakeLms)
    library: FakeLibrarySourceReader = field(default_factory=FakeLibrarySourceReader)
    fetcher: FakeWebFetcher = field(default_factory=FakeWebFetcher)
    transcripts: FakeTranscriptProvider = field(default_factory=FakeTranscriptProvider)
    terms: FakeTermCalendar = field(default_factory=FakeTermCalendar)
    classwork: FakeClasswork = field(init=False)

    def __post_init__(self) -> None:
        """The classwork fake reads the schedule fake."""
        self.classwork = FakeClasswork(self.schedule)
