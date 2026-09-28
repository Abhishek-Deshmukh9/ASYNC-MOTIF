import logging
from typing import List, Optional
import numpy as np
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine, AsyncSessionLocal
from app.models.feedback import FeedbackItem

logger = logging.getLogger(__name__)

# Model configuration
DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384

_model_instance = None


def get_embedding_model(model_name: str = DEFAULT_MODEL_NAME):
    """Lazy-loaded singleton instance of the SentenceTransformer model."""
    global _model_instance
    if _model_instance is None:
        logger.info(f"Loading SentenceTransformer embedding model: {model_name}...")
        from sentence_transformers import SentenceTransformer
        _model_instance = SentenceTransformer(model_name)
        logger.info("SentenceTransformer model loaded successfully.")
    return _model_instance


def embed_texts(texts: List[str], batch_size: int = 64) -> List[List[float]]:
    """
    Generate dense vector embeddings using all-MiniLM-L6-v2.
    Output: List of 384-dimensional float lists.
    """
    if not texts:
        return []

    model = get_embedding_model()
    # Normalize embeddings to unit sphere for cosine distance
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return [vec.tolist() for vec in embeddings]


async def fetch_and_embed_unembedded_batch(
    session: AsyncSession,
    batch_size: int = 50,
) -> int:
    """
    Fetches one batch of records where embedding IS NULL, computes MiniLM vectors,
    and updates the pgvector column. Returns the number of items updated.
    """
    query = (
        select(FeedbackItem.id, FeedbackItem.clean_content, FeedbackItem.content)
        .where(FeedbackItem.embedding.is_(None))
        .limit(batch_size)
    )
    result = await session.execute(query)
    rows = result.all()

    if not rows:
        return 0

    item_ids = [row[0] for row in rows]
    texts_to_embed = [row[1] if row[1] else row[2] for row in rows]

    logger.info(f"Computing embeddings for batch of {len(texts_to_embed)} feedback items...")
    vectors = embed_texts(texts_to_embed)

    # Update in database
    for item_id, vector in zip(item_ids, vectors):
        await session.execute(
            update(FeedbackItem)
            .where(FeedbackItem.id == item_id)
            .values(embedding=vector)
        )

    await session.commit()
    logger.info(f"Persisted {len(vectors)} vector embeddings into pgvector column.")
    return len(vectors)


async def embed_all_unembedded_items(batch_size: int = 50) -> int:
    """
    Iteratively processes all feedback items in Supabase / PostgreSQL missing embeddings.
    """
    total_embedded = 0
    async with AsyncSessionLocal() as session:
        while True:
            count = await fetch_and_embed_unembedded_batch(session, batch_size=batch_size)
            if count == 0:
                break
            total_embedded += count
            logger.info(f"Total items embedded so far: {total_embedded}")

    return total_embedded
