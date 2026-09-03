"""Reference-data routes for the PFW proxy: document-code table and
reflections resources (carved out of create_proxy_app() — audit F4)."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
import time
from typing import Optional

from ...shared.safe_logger import get_safe_logger
from ..server import _check_proxy_token


logger = get_safe_logger(__name__)

router = APIRouter()


@router.get("/reflections")
async def list_reflections(mcp_type: Optional[str] = None, tags: Optional[str] = None):
    """
    List available reflection resources for MCP Resources capability

    Query Parameters:
        mcp_type: Filter by MCP type (pfw, fpd, ptab)
        tags: Comma-separated list of tags to filter by
    """
    try:
        from ...reflections.reflection_manager import get_reflection_manager

        # Parse tags parameter
        tag_list = None
        if tags:
            tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()]

        reflection_manager = get_reflection_manager()
        resources = reflection_manager.list_resources(mcp_type=mcp_type, tags=tag_list)

        return {
            "success": True,
            "resources": resources,
            "count": len(resources),
            "filters": {
                "mcp_type": mcp_type,
                "tags": tag_list
            }
        }

    except Exception:
        logger.exception("Error listing reflections")
        raise

@router.get("/reflections/{mcp_type}/{resource_name}")
async def get_reflection_resource(mcp_type: str, resource_name: str, format: str = "markdown"):
    """
    Get specific reflection resource content

    Path Parameters:
        mcp_type: MCP type (pfw, fpd, ptab)
        resource_name: Resource name identifier

    Query Parameters:
        format: Response format (markdown, json, summary)
    """
    try:
        from ...reflections.reflection_manager import get_reflection_manager

        resource_path = f"/reflections/{mcp_type}/{resource_name}"
        reflection_manager = get_reflection_manager()

        if format == "summary":
            # Get resource metadata and summary
            resources = reflection_manager.list_resources(mcp_type=mcp_type)
            matching_resource = None
            for resource in resources:
                if resource['uri'] == resource_path:
                    matching_resource = resource
                    break

            if not matching_resource:
                raise HTTPException(status_code=404, detail="Resource not found")

            reflection = reflection_manager.get_reflection_by_name(resource_name)
            if reflection:
                return {
                    "success": True,
                    "resource": matching_resource,
                    "summary": reflection.get_summary(),
                    "format": "summary"
                }

        elif format == "json":
            # Get resource as JSON metadata
            reflection = reflection_manager.get_reflection_by_name(resource_name)
            if reflection:
                return {
                    "success": True,
                    "metadata": reflection.get_metadata(),
                    "content_available": True,
                    "format": "json"
                }

        else:
            # Get full content as markdown (default)
            content = reflection_manager.get_resource(resource_path)
            if content:
                return Response(
                    content=content,
                    media_type="text/markdown",
                    headers={
                        "Content-Type": "text/markdown; charset=utf-8",
                        "X-Resource-Type": "USPTO-MCP-Reflection",
                        "X-MCP-Type": mcp_type,
                        "X-Resource-Name": resource_name
                    }
                )

        raise HTTPException(status_code=404, detail="Resource not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting reflection resource {resource_path}: {e}")
        raise HTTPException(status_code=500, detail="Resource access failed")

@router.get("/reflections/stats", dependencies=[Depends(_check_proxy_token)])
async def get_reflection_stats():
    """Get reflection statistics for monitoring"""
    try:
        from ...reflections.reflection_manager import get_reflection_manager

        reflection_manager = get_reflection_manager()
        stats = reflection_manager.get_statistics()

        return {
            "success": True,
            "stats": stats,
            "endpoints": {
                "list_resources": "/reflections",
                "get_resource": "/reflections/{mcp_type}/{resource_name}",
                "statistics": "/reflections/stats"
            }
        }

    except Exception:
        logger.exception("Error getting reflection stats")
        raise


@router.get("/doc-codes")
async def get_doc_codes():
    """
    Serve USPTO Document Code Decoder Table

    This endpoint provides a formatted markdown table of USPTO document codes
    for patent prosecution, PTAB proceedings, and FPD petitions.

    Source: https://www.uspto.gov/patents/apply/filing-online/efs-info-document-description
    """
    try:
        # One parser, shared with the MCP resource `uspto://pfw/doc-codes`
        # (main.read_doc_codes). They were two copies that had drifted, so the
        # same CSV rendered differently per endpoint (audit D-1).
        from ...reference.doc_codes import build_doc_code_table

        result = build_doc_code_table()
        result += (
            "\n"
            f"\n**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
        )
        logger.info(f"Generated document codes table ({len(result)} characters)")

        return Response(
            content=result,
            media_type="text/markdown",
            headers={
                "Content-Type": "text/markdown; charset=utf-8",
                "X-Resource-Type": "USPTO-DOC-CODES",
                "X-Source": "USPTO-EFS-Web",
                "Cache-Control": "public, max-age=3600"  # Cache for 1 hour
            }
        )

    except Exception:
        logger.exception("Error generating document codes table")
        return JSONResponse(
            status_code=500,
            content={
                "error": True,
                "message": "Failed to generate document codes table",
                "guidance": "Check that reference/Document_Descriptions_List.csv exists in project root"
            }
        )

