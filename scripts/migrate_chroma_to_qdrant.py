"""
Migrazione ChromaDB → Qdrant
Migra 15.483 documenti dalla KB locale al Qdrant centrale.
"""
import asyncio
import sys
from pathlib import Path

# Aggiungi root al path
sys.path.insert(0, str(Path(__file__).parent.parent))

async def migrate():
    import chromadb
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance, VectorParams, PointStruct
    )
    from core.embedding_provider import FastEmbedProvider
    import uuid

    print("=== Migrazione ChromaDB → Qdrant ===\n")

    # Connessione ChromaDB
    print("Connessione ChromaDB...")
    chroma = chromadb.PersistentClient(
        path="data/chroma_backup"
    )
    source = chroma.get_collection("neural_hub_knowledge")
    total = source.count()
    print(f"Documenti da migrare: {total}\n")

    # Connessione Qdrant (tunnel SSH locale)
    print("Connessione Qdrant...")
    qdrant = QdrantClient(host="localhost", port=6333)

    # Crea collection se non esiste
    collection_name = "global_knowledge"
    existing = [
        c.name for c in qdrant.get_collections().collections
    ]
    if collection_name not in existing:
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=384,
                distance=Distance.COSINE
            )
        )
        print(f"Collection '{collection_name}' creata.")
    else:
        count = qdrant.count(collection_name).count
        print(
            f"Collection '{collection_name}' esiste "
            f"({count} documenti già presenti)."
        )

    # Embedding provider
    print("Inizializzazione FastEmbed...")
    embedder = FastEmbedProvider()

    # Migrazione a batch
    batch_size = 100
    offset = 0
    migrated = 0
    errors = 0

    print(f"\nMigrazione in corso (batch={batch_size})...")

    while offset < total:
        try:
            # Leggi da ChromaDB
            results = source.get(
                limit=batch_size,
                offset=offset,
                include=["documents", "metadatas"]
            )

            docs = results["documents"]
            metas = results["metadatas"]
            ids = results["ids"]

            if not docs:
                break

            # Genera embeddings
            embeddings = await embedder.embed(docs)

            # Prepara punti Qdrant
            points = []
            for i, (doc, meta, doc_id) in enumerate(
                zip(docs, metas, ids)
            ):
                # Payload con tutti i metadati
                payload = {
                    "content": doc[:1000],
                    "source_id": doc_id,
                    "tenant_id": "global",
                    "type": meta.get("type", "unknown"),
                    "name": meta.get("name", ""),
                    "plugin": meta.get("plugin", ""),
                    "description": meta.get(
                        "description", ""
                    )[:500],
                    "tags": meta.get("tags", ""),
                    "file_path": meta.get(
                        "file_path", ""
                    ),
                }

                points.append(PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embeddings[i],
                    payload=payload
                ))

            # Carica su Qdrant
            qdrant.upsert(
                collection_name=collection_name,
                points=points
            )

            migrated += len(points)
            offset += batch_size

            # Progress
            pct = (migrated / total) * 100
            print(
                f"  {migrated}/{total} "
                f"({pct:.1f}%) migrati...",
                end="\r"
            )

        except Exception as e:
            print(f"\n  Errore batch offset={offset}: {e}")
            errors += 1
            offset += batch_size
            continue

    print(f"\n\n=== Migrazione completata ===")
    print(f"Migrati:  {migrated}")
    print(f"Errori:   {errors}")

    # Verifica finale
    final_count = qdrant.count(collection_name).count
    print(f"Qdrant:   {final_count} documenti totali")

    # Stats per tipo
    print("\nDistribuzione per tipo:")
    for doc_type in [
        "skill", "agent", "command", "docs", "readme"
    ]:
        result = qdrant.count(
            collection_name=collection_name,
            count_filter={
                "must": [{
                    "key": "type",
                    "match": {"value": doc_type}
                }]
            }
        )
        if result.count > 0:
            print(f"  {doc_type}: {result.count}")

if __name__ == "__main__":
    asyncio.run(migrate())
