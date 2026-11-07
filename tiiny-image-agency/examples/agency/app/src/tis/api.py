"""The public API: the HTTP entry point for the Tiiny Image Agency.

This module implements the HTTP API for the Tiiny Image Agency. It is the
only surface area for external callers. All paths go through the Agency,
which is the single source of truth for the inference pipeline.
"""
from __future__ import annotations

import asyncio
import json
import queue
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from .service import Agency
from .models import ModelChoice
from .registry import ModelSpec
from .planner import PlannerError
from .resolver import ResolverError
from .roles import RoleError
from .device import DeviceError


def create_app(agency: Agency | None = None, settings = None) -> FastAPI:
    """Create the Tiiny Image Agency FastAPI application.
    
    The agency is stored on app.state.agency. Every route reads it from there,
    so a test can hand the app an Agency built on a FakeDevice.
    
    When `agency` is None, build one from `settings` (or `load_settings()`).
    Creating the app must not touch the network. Constructing an Agency is
    offline; do not call the device in create_app.
    
    Args:
        agency: The Agency to use, or None to create one from settings
        settings: Settings to use when creating an agency
        
    Returns:
        The FastAPI application
    """
    # Set the agency on the app state
    if agency is None:
        from .config import load_settings
        if settings is None:
            settings = load_settings()
        from .service import Agency
        agency = Agency(settings)

    # Create the lifespan manager for shutdown
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup would go here, but we have nothing to do.
        yield
        # Shutdown - close the agency. It owns the one worker thread, and
        # a worker left running would keep the appliance held after the
        # server that asked for it is gone.
        agency.close()

    # Create the app with lifespan
    app = FastAPI(
        title="Tiiny Image Agency",
        description="An API for the Tiiny Image Agency",
        version="0.1.0",
        lifespan=lifespan,
    )

    # The agency is on the app state from the moment the app is BUILT, not
    # from the moment its lifespan runs. A test that uses TestClient without
    # a context manager never runs the lifespan, and a route that read
    # app.state.agency would find nothing there.
    app.state.agency = agency
    
    # Routes
    @app.get("/v1/models")
    async def get_models():
        """Get the registry of image models."""
        # Get the registry from the agency and build the response
        registry = agency.registry
        models = []
        for model_spec in registry.models:
            # Build the model object as specified in the requirements
            model_dict = {
                "id": model_spec.id,
                "role": model_spec.role,
                "npu_usage": model_spec.npu_usage,
                "kind": model_spec.kind,
                "alpha": model_spec.alpha,
                "text_rendering": model_spec.text_rendering,
                "quality": model_spec.quality,
                "speed": model_spec.speed,
                "artifacts": model_spec.artifact,
                "styles": model_spec.style,
                "dialect": model_spec.dialect,
                "sizes_verified": model_spec.sizes_verified,
                # Listed is not installed. The resolver will not pick a
                # model that is not on disk, and a client that cannot
                # see that cannot explain why the same request always
                # gets the same model.
                "downloaded": model_spec.downloaded,
            }
            models.append(model_dict)
        
        return {"models": models}

    @app.get("/v1/models/card")
    async def model_card(model_id: str):
        """The research card for a model: what it was measured to do.

        The model id is a QUERY parameter, not a path segment, because
        the ids contain slashes — "Tongyi-MAI/Z-Image-Turbo" — and a
        path segment cannot carry one.

        404 when the model has not been researched. The cards are written
        by the research loop, which measures models on the appliance —
        the device's own description of a model cannot be trusted.
        """
        card = agency.model_card(model_id)
        if card is None:
            raise HTTPException(status_code=404,
                                detail="No research card for this model")
        return card

    @app.get("/v1/roles")
    async def get_roles():
        """The guide: which models can hold the conversation and the critic.

        Every conversational model the appliance offers, whether or not it
        can SEE an image, what each costs in NPU, and whether it is on the
        device right now.

        The `vision` flag is the one that matters. A critic that can see
        the image judges the PICTURE; one that cannot judges only the
        prompt, and cannot catch a generation that simply came out wrong.
        """
        return agency.role_options()

    @app.post("/v1/roles")
    async def set_roles(body: RoleRequest):
        """Choose who talks and who judges.

        The guide above says which models can see an image; this is how
        one is chosen. The choice is immediate - it applies to the next
        job, and the next job is the one that matters.
        """
        try:
            return agency.set_roles(conversation=body.conversation,
                                    critic=body.critic)
        except RoleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/npu")
    async def get_npu():
        """Get the current NPU usage and resident models."""
        return agency.npu()

    @app.post("/v1/plan")
    async def plan(request: PlanRequest):
        """Plan an image generation request."""
        if not request.request.strip():
            raise HTTPException(status_code=400, detail="Request cannot be empty")
            
        try:
            result = agency.plan(
                request.request,
                request.width,
                request.height,
                request.session_id,
                request.model_id
            )
            return result
        except PlannerError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except ResolverError as exc:
            # A refusal, not a fault: the request is answerable in
            # principle, but no model downloaded on this appliance can
            # answer it. The message names the model to download, so the
            # caller is not left guessing.
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/v1/generate", status_code=status.HTTP_202_ACCEPTED)
    async def generate(request: GenerateRequest):
        """Generate an image from a request.

        202 ACCEPTED, not 200: the work has been QUEUED, not done. The
        appliance takes 54-200 seconds for one image, so a client that
        read 200 would reasonably believe the image was ready.
        """
        if not request.request.strip():
            raise HTTPException(status_code=400, detail="Request cannot be empty")

        # Create job and return immediately
        job_id = agency.generate(
            request.request,
            session_id=request.session_id,
            width=request.width,
            height=request.height,
            model_id=request.model_id
        )

        # Return the job info immediately without waiting
        return {
            "job_id": job_id,
            "session_id": request.session_id,
            "status": "queued"
        }

    @app.post("/v1/iterate", status_code=status.HTTP_202_ACCEPTED)
    async def iterate(request: IterateRequest):
        """Iterate on an existing asset with new feedback.

        202 ACCEPTED, for the same reason as generate: the revision is
        queued, not finished.
        """
        if not request.feedback.strip():
            raise HTTPException(status_code=400, detail="Feedback cannot be empty")

        # Create job and return immediately
        job_id = agency.iterate(
            request.asset_id,
            request.feedback,
            session_id=request.session_id
        )

        # Return the job info immediately without waiting
        return {
            "job_id": job_id,
            "session_id": request.session_id,
            "status": "queued"
        }

    @app.get("/v1/assets/{asset_id}")
    async def get_asset(asset_id: str):
        """Get the PNG of an asset."""
        asset = agency.get_asset(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="Asset not found")
            
        # Return the PNG bytes exactly as stored
        return Response(content=asset.png, media_type="image/png")

    @app.get("/v1/assets/{asset_id}/lineage")
    async def get_lineage(asset_id: str):
        """Get the lineage of an asset."""
        asset = agency.get_asset(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="Asset not found")
        
        return asset.lineage

    @app.get("/v1/session/{session_id}/events")
    async def stream_events(session_id: str, job_id: str | None = None):
        """Stream the events for a session.

        The bus hands out a THREADING queue: the worker publishes to it
        from a worker thread, and the route reads it from the event loop.
        So the read is pushed onto a thread with ``asyncio.to_thread``.
        Awaiting a threading queue directly would await a bytes object,
        and the empty case raises ``queue.Empty`` — not
        ``asyncio.QueueEmpty``, which is a different exception entirely.

        ``job_id`` names the job the caller is waiting for. The bus
        REPLAYS a session's recent events, so a subscriber sees the
        terminal events of EARLIER jobs — and ending the stream on one
        of those cut it off before the caller's own job had even
        started. With a job_id, only that job's terminal event ends the
        stream. Without one, any terminal event does, which is the
        behaviour a session-wide watcher wants.
        """
        async def event_stream():
            subscriber = agency.events.subscribe(session_id)
            try:
                while True:
                    try:
                        event = await asyncio.to_thread(
                            subscriber.get, True, 1.0)
                    except queue.Empty:
                        # Nothing for a second. The client may simply be
                        # quiet; the loop continues so the stream stays
                        # open rather than ending on a lull.
                        continue
                    except ValueError:
                        # The queue was closed, so the session is over.
                        break
                    yield f"data: {json.dumps(event.to_dict())}\n\n"
                    if event.type in ("job.finished", "job.failed"):
                        if job_id is None or event.data.get("job_id") == job_id:
                            break
            finally:
                # Drop THIS subscriber, not the whole session: another
                # client may be watching the same session, and taking
                # the session down would silence it too.
                agency.events.unsubscribe_queue(subscriber)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )

    @app.get("/v1/health")
    async def health():
        """Check the health of the application."""
        return agency.health()

    # The work surface. It is three static files with no build step, and
    # they are mounted here so that ONE port serves both the API and
    # the screen that drives it. The mount is added LAST so it cannot
    # shadow any of the /v1 routes above.
    #
    # The files also work when served from a plain static server, which
    # is what the ?api= query parameter is for: the surface may be
    # served from somewhere other than the API.
    web_dir = _web_dir()
    if web_dir is not None:
        app.mount("/", StaticFiles(directory=str(web_dir), html=True),
                  name="web")

    return app


def _web_dir() -> Path | None:
    """Where the work surface lives, or None if it is not there.

    A missing web directory is not an error: the API is still a valid
    API, and the surface can be served from anywhere.
    """
    root = Path(__file__).resolve().parents[3]
    candidate = root / "app" / "web"
    if (candidate / "index.html").is_file():
        return candidate
    return None


# Request models
from pydantic import BaseModel
from typing import Optional


class PlanRequest(BaseModel):
    """Request body for the /v1/plan endpoint."""
    request: str
    width: int = 1024
    height: int = 1024
    session_id: str = "default"
    #: A model the user chose. Honoured when it can do the job; the
    #: plan says so when it cannot.
    model_id: str = ""


class RoleRequest(BaseModel):
    """A request to change who talks and who judges.

    Both are optional: send one, or both, or neither to read the guide.
    """
    conversation: str | None = None
    critic: str | None = None


class GenerateRequest(BaseModel):
    """Request body for the /v1/generate endpoint."""
    request: str
    width: int = 1024
    height: int = 1024
    session_id: str = "default"
    #: A model the user chose, or empty to let the resolver decide.
    model_id: str = ""


class IterateRequest(BaseModel):
    """Request body for the /v1/iterate endpoint."""
    asset_id: str
    feedback: str
    session_id: str = "default"