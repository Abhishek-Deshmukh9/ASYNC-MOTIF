import logging
from typing import Dict, List, Tuple, Any
import numpy as np
from sklearn.cluster import HDBSCAN

logger = logging.getLogger(__name__)


class ClusterResult:
    """Encapsulates cluster groupings, metrics, and isolated noise points."""

    def __init__(
        self,
        clusters: Dict[int, List[Dict[str, Any]]],
        noise_items: List[Dict[str, Any]],
        cohesion_scores: Dict[int, float],
        exemplars: Dict[int, List[Dict[str, Any]]],
    ):
        self.clusters = clusters  # {cluster_id: [item1, item2, ...]}
        self.noise_items = noise_items  # items with label -1
        self.cohesion_scores = cohesion_scores  # {cluster_id: float}
        self.exemplars = exemplars  # {cluster_id: [top_representative_items]}

    @property
    def total_dense_clusters(self) -> int:
        return len(self.clusters)

    @property
    def total_noise_count(self) -> int:
        return len(self.noise_items)


def cluster_feedback_embeddings(
    items_with_embeddings: List[Dict[str, Any]],
    min_cluster_size: int = 4,
    min_samples: int = 2,
) -> ClusterResult:
    min_cluster_size = min_cluster_size or 4
    min_samples = min_samples or 2
    if not items_with_embeddings:
        return ClusterResult(clusters={}, noise_items=[], cohesion_scores={}, exemplars={})

    # Prepare vector matrix
    vectors = [item["embedding"] for item in items_with_embeddings]
    X = np.array(vectors, dtype=np.float32)

    if len(X) < min_cluster_size:
        logger.warning(f"Item count ({len(X)}) is smaller than min_cluster_size ({min_cluster_size}).")
        return ClusterResult(clusters={}, noise_items=items_with_embeddings, cohesion_scores={}, exemplars={})

    # Configure and fit HDBSCAN
    # Metric 'euclidean' on unit-normalized vectors directly preserves cosine distance
    def fit(allow_single_cluster: bool):
        return HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            metric="euclidean",
            cluster_selection_method="eom",  # Excess of Mass
            allow_single_cluster=allow_single_cluster,
            copy=True,
        ).fit_predict(X)

    # Look for separate topics first. Allowing a single cluster up front makes a small project
    # (tens of passages about several problems) collapse into one theme, because the topics sit
    # close together compared with the outliers. Only if no topics are found at all, check
    # whether everything is one problem. On the 300-item demo corpus the labels are identical.
    labels = fit(allow_single_cluster=False)
    if (labels == -1).all():
        labels = fit(allow_single_cluster=True)

    dense_clusters: Dict[int, List[Dict[str, Any]]] = {}
    noise_items: List[Dict[str, Any]] = []
    cluster_vectors: Dict[int, List[np.ndarray]] = {}

    for idx, (label, item) in enumerate(zip(labels, items_with_embeddings)):
        enriched_item = dict(item)
        enriched_item["cluster_label"] = int(label)

        if label == -1:
            # Noise isolation bucket (Rule 1.2)
            noise_items.append(enriched_item)
        else:
            dense_clusters.setdefault(int(label), []).append(enriched_item)
            cluster_vectors.setdefault(int(label), []).append(X[idx])

    # Calculate cohesion scores and find exemplars (medoids) for each dense cluster
    cohesion_scores: Dict[int, float] = {}
    exemplars: Dict[int, List[Dict[str, Any]]] = {}

    for cluster_id, c_items in dense_clusters.items():
        c_vecs = np.array(cluster_vectors[cluster_id])
        if len(c_vecs) <= 1:
            cohesion_scores[cluster_id] = 1.0
            exemplars[cluster_id] = c_items
            continue

        # Compute pairwise distance matrix within cluster
        # Cosine distance for unit vectors = 1 - dot_product
        dot_matrix = np.dot(c_vecs, c_vecs.T)
        dist_matrix = np.clip(1.0 - dot_matrix, 0.0, 2.0)
        mean_dist = float(np.mean(dist_matrix))

        # Cohesion score: 1.0 for very tight clusters, decreases as spread increases
        cohesion = 1.0 / (1.0 + mean_dist)
        cohesion_scores[cluster_id] = round(cohesion, 3)

        # Medoid calculation: item with minimum average distance to all others
        avg_distances = np.mean(dist_matrix, axis=1)
        sorted_indices = np.argsort(avg_distances)

        # Select top 5 exemplars closest to cluster medoid
        top_k = min(5, len(c_items))
        exemplars[cluster_id] = [c_items[i] for i in sorted_indices[:top_k]]

    logger.info(
        f"HDBSCAN clustering complete: {len(dense_clusters)} dense clusters found, "
        f"{len(noise_items)} noise points isolated."
    )

    return ClusterResult(
        clusters=dense_clusters,
        noise_items=noise_items,
        cohesion_scores=cohesion_scores,
        exemplars=exemplars,
    )
