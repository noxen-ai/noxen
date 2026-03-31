"""API Routes: Health & Status."""

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health(request: Request):
    bootstrap_result = getattr(request.app.state, "bootstrap_result", None)

    if bootstrap_result is None:
        return {
            "status": "ok",
            "version": "0.3.0",
            "service": "Noxen",
            "bootstrap": None,
        }

    # Determine overall status
    if not bootstrap_result.success:
        status = "error"
    elif bootstrap_result.warnings:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "version": "0.3.0",
        "service": "Noxen",
        "bootstrap": {
            "success": bootstrap_result.success,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                }
                for c in bootstrap_result.checks
            ],
            "errors": bootstrap_result.errors,
            "warnings": bootstrap_result.warnings,
        },
    }


@router.get("/api/qdrant/status")
async def qdrant_status():
    """Stato di Qdrant: health, collections, version."""
    try:
        from core.qdrant_client import NoxenQdrantClient, COLLECTIONS

        instance = NoxenQdrantClient.get_instance()
        client = instance.client

        # Health check
        healthy = await instance.health_check()

        # Collection counts
        collections_info = {}
        for name in COLLECTIONS:
            try:
                info = client.get_collection(name)
                collections_info[name] = {"count": info.points_count or 0}
            except Exception:
                collections_info[name] = {"count": 0}

        # Qdrant version (best-effort)
        qdrant_version = "unknown"
        try:
            # Try to get version from telemetry or cluster info
            from qdrant_client.http.models import CollectionsResponse
            qdrant_version = getattr(client, '_server_version', 'unknown')
            if qdrant_version == 'unknown':
                # Fallback: try HTTP call
                import httpx
                resp = httpx.get(f"{instance._url}/", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    qdrant_version = data.get("version", "unknown")
        except Exception:
            pass

        return {
            "status": "ok" if healthy else "error",
            "collections": collections_info,
            "qdrant_version": qdrant_version,
        }

    except RuntimeError:
        # NoxenQdrantClient non inizializzato
        return {
            "status": "not_initialized",
            "collections": {},
            "qdrant_version": "unknown",
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "collections": {},
            "qdrant_version": "unknown",
        }
