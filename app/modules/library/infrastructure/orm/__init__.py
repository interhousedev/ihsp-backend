"""ORM models of the library module (schema ``library``)."""

from app.modules.library.infrastructure.orm.external import (
    ExternalFeed,
    ExternalFieldMap,
)
from app.modules.library.infrastructure.orm.item import (
    BookDetails,
    ExternalDetails,
    Item,
    ItemFile,
    ItemPage,
    ItemStat,
    MaterialDetails,
)
from app.modules.library.infrastructure.orm.labels import (
    Author,
    ItemAuthor,
    ItemTag,
    Tag,
)
from app.modules.library.infrastructure.orm.moderation import (
    BookSuggestion,
    ItemEvent,
    ItemReport,
    Sanction,
)
from app.modules.library.infrastructure.orm.reader import (
    Annotation,
    BookPlan,
    LessonItemRef,
    ReadingProgress,
    ShelfEntry,
)
from app.modules.library.infrastructure.orm.taxonomy import (
    Collection,
    CollectionItem,
    ItemSubject,
    ItemTopic,
    ReadingList,
    ReadingListItem,
    Subject,
    Topic,
)

__all__ = [
    "Annotation",
    "Author",
    "BookDetails",
    "BookPlan",
    "BookSuggestion",
    "Collection",
    "CollectionItem",
    "ExternalDetails",
    "ExternalFeed",
    "ExternalFieldMap",
    "Item",
    "ItemAuthor",
    "ItemEvent",
    "ItemFile",
    "ItemPage",
    "ItemReport",
    "ItemStat",
    "ItemTag",
    "ItemSubject",
    "ItemTopic",
    "LessonItemRef",
    "MaterialDetails",
    "ReadingList",
    "ReadingListItem",
    "ReadingProgress",
    "Sanction",
    "ShelfEntry",
    "Subject",
    "Tag",
    "Topic",
]
