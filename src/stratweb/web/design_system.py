"""Versioned visual language and its local component reference page."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from stratweb.web.rendering import render_template


def design_system_router() -> APIRouter:
    """Expose a read-only reference page for visual regression and development."""

    router = APIRouter()

    @router.get("/ui/style-guide", response_class=HTMLResponse, include_in_schema=False)
    def style_guide() -> HTMLResponse:
        return HTMLResponse(
            render_template(
                "style_guide.html",
                title="Design system",
                match_context=None,
            )
        )

    return router
