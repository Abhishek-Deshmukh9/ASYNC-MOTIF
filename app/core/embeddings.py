import asyncio
import logging
from typing import List, Optional
import numpy as np
from sqlalchemy import select, update, bindparam
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


def _embed_texts_sync(texts: List[str], batch_size: int = 64) -> List[List[float]]:
    """
    CPU-bound embedding generation — runs in a thread pool executor so the
    asyncio event loop is never blocked (B-3 fix).
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


async def embed_texts(texts: List[str], batch_size: int = 64) -> List[List[float]]:
    """
    Generate dense vector embeddings using all-MiniLM-L6-v2.
    Output: List of 384-dimensional float lists.
    Runs the CPU-intensive work in a thread pool to avoid event-loop starvation.
    """
    if not texts:
        return []
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _embed_texts_sync, texts, batch_size)


async def fetch_and_embed_unembedded_batch(
    session: AsyncSession,
    batch_size: int = 50,
) -> int:
    """
    Fetches one batch of records where embedding IS NULL, computes MiniLM vectors,
    and updates the pgvector column. Returns the number of items updated.
    Uses batched UPDATE to avoid N+1 queries (B-4 fix).
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
    vectors = await embed_texts(texts_to_embed)

    # Batch update: single executemany instead of N individual UPDATEs (B-4 fix)
    update_params = [
        {"_item_id": item_id, "_embedding": vector}
        for item_id, vector in zip(item_ids, vectors)
    ]
    stmt = (
        update(FeedbackItem)
        .where(FeedbackItem.id == bindparam("_item_id"))
        .values(embedding=bindparam("_embedding"))
    )
    await session.execute(stmt, update_params)
    await session.commit()

    logger.info(f"Persisted {len(vectors)} vector embeddings into pgvector column (batched).")
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
