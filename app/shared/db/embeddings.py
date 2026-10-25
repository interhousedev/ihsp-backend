"""ORM model of `vectors.embeddings`: one vector per (text hash, model).

Shared kernel, not a module's private table: every module that wants a text found by
meaning (notebooks passages now, library items later) keeps its text where it is and
looks the vector up by `content_hash` (sha256 of the text, as in
`notebooks.domain.passage_hash`). Equal texts therefore share one vector across
documents, notebooks and students, and the text is embedded (paid for) once.
"""

from app.shared.db.base import Base, TimestampMixin
from app.shared.db.halfvec import HalfVec

from sqlalchemy import CHAR, CheckConstraint, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

EMBEDDING_DIMS = 1024
"""Size of every stored vector. 1024 is native to bge-m3, multilingual-e5-large and
Voyage, and a Matryoshka cut of the Qwen3 models, so a model can change without a
schema change. A different size means a new column (or table) in a new migration."""

HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64


class Embedding(TimestampMixin, Base):
    """The vector of one text under one model (`halfvec`, cosine distance)."""

    __tablename__ = "embeddings"
    __table_args__ = (
        CheckConstraint("dims = vector_dims(embedding)", name="dims"),
        Index(
            "ix_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": HNSW_M, "ef_construction": HNSW_EF_CONSTRUCTION},
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
        ),
        {"schema": "vectors"},
    )

    content_hash: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    dims: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(HalfVec(EMBEDDING_DIMS))
