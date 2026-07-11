"""Instance-scoped documentation snapshots, retrieval, and grounded answers."""

from wiicon5.instance_knowledge.index import InstanceKnowledgeBase, KnowledgeHit
from wiicon5.instance_knowledge.models import KnowledgePage, KnowledgeSnapshotManifest
from wiicon5.instance_knowledge.storage import KnowledgeRepository
from wiicon5.instance_knowledge.sync import KnowledgeSyncResult, KnowledgeSyncService

__all__ = [
    "InstanceKnowledgeBase",
    "KnowledgeHit",
    "KnowledgePage",
    "KnowledgeRepository",
    "KnowledgeSnapshotManifest",
    "KnowledgeSyncResult",
    "KnowledgeSyncService",
]
