"""Reference-data routes for the PFW proxy: document-code table and
reflections resources (carved out of create_proxy_app() — audit F4)."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response
import time
from typing import Optional

from ...shared.safe_logger import get_safe_logger


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

    except Exception as e:
        logger.error(f"Error listing reflections: {e}")
        return {"success": False, "error": str(e)}

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
        raise HTTPException(status_code=500, detail=f"Resource access failed: {str(e)}")

@router.get("/reflections/stats")
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

    except Exception as e:
        logger.error(f"Error getting reflection stats: {e}")
        return {"success": False, "error": str(e)}


@router.get("/doc-codes")
async def get_doc_codes():
    """
    Serve USPTO Document Code Decoder Table

    This endpoint provides a formatted markdown table of USPTO document codes
    for patent prosecution, PTAB proceedings, and FPD petitions.

    Source: https://www.uspto.gov/patents/apply/filing-online/efs-info-document-description
    """
    try:
        import csv
        import os

        # Find the CSV file relative to project root
        # Get project root (go up from src/patent_filewrapper_mcp/proxy/)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.join(current_dir, "..", "..", "..")
        csv_path = os.path.join(project_root, "reference", "Document_Descriptions_List.csv")

        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Document_Descriptions_List.csv not found at {csv_path}")

        # Parse CSV and format as markdown
        output = []
        output.append("# USPTO Document Code Decoder Table")
        output.append("")
        output.append("**Source**: [USPTO EFS-Web Document Description List](https://www.uspto.gov/patents/apply/filing-online/efs-info-document-description)")
        output.append("**Updated**: April 27, 2022")
        output.append("")
        output.append("This table provides document codes used in USPTO patent prosecution, PTAB proceedings, and FPD petitions.")
        output.append("")

        prosecution_codes = []
        ptab_codes = []
        fpd_codes = []

        # Try multiple encodings to handle the CSV file
        encodings_to_try = ['utf-8', 'utf-8-sig', 'latin1', 'cp1252', 'iso-8859-1']

        for encoding in encodings_to_try:
            try:
                logger.info(f"Trying to read CSV with encoding: {encoding}")
                with open(csv_path, 'r', encoding=encoding) as file:
                    csv_reader = csv.reader(file)
                    headers = None

                    for row in csv_reader:
                        if not headers:
                            headers = row
                            continue

                        if len(row) >= 4:
                            category = row[0].strip()
                            description = row[1].strip()
                            business_process = row[2].strip()
                            doc_code = row[3].strip()

                            if doc_code and doc_code != "DOC CODE":
                                # Clean up description and business process
                                description = description.replace('\n', ' ').replace('\r', ' ')
                                business_process = business_process.replace('\n', ' ').replace('\r', ' ')

                                # Remove any problematic characters
                                description = ''.join(char if ord(char) < 128 else '?' for char in description)
                                business_process = ''.join(char if ord(char) < 128 else '?' for char in business_process)

                                # Limit lengths for readability
                                if len(description) > 120:
                                    description = description[:117] + "..."
                                if len(business_process) > 100:
                                    business_process = business_process[:97] + "..."

                                # Escape pipe characters for markdown table
                                description = description.replace('|', '\\|')
                                business_process = business_process.replace('|', '\\|')

                                code_entry = {
                                    'code': doc_code,
                                    'description': description,
                                    'process': business_process,
                                    'category': category
                                }

                                if 'PTAB' in category:
                                    ptab_codes.append(code_entry)
                                elif 'FPD' in category or 'Final Petition Decision' in category:
                                    fpd_codes.append(code_entry)
                                else:
                                    prosecution_codes.append(code_entry)

                logger.info(f"Successfully read CSV with {encoding} encoding")
                break  # Success - exit the encoding loop

            except UnicodeDecodeError as e:
                logger.warning(f"Failed to read CSV with {encoding} encoding: {e}")
                continue
            except Exception as e:
                logger.error(f"Error reading CSV with {encoding} encoding: {e}")
                continue
        else:
            # If we get here, all encodings failed
            raise FileNotFoundError(f"Unable to read CSV file with any of the attempted encodings: {encodings_to_try}")

        # Add common prosecution codes section
        output.append("## Common Prosecution Document Codes")
        output.append("")
        output.append("| Code | Description | Business Process |")
        output.append("|------|-------------|------------------|")

        # Sort prosecution codes by code for better organization
        prosecution_codes.sort(key=lambda x: x['code'])

        for code_info in prosecution_codes[:60]:  # Limit to first 60 for readability
            output.append(f"| `{code_info['code']}` | {code_info['description']} | {code_info['process']} |")

        # Add PTAB codes section if available
        if ptab_codes:
            output.append("")
            output.append("## PTAB (Patent Trial and Appeal Board) Document Codes")
            output.append("")
            output.append("| Code | Description | Business Process |")
            output.append("|------|-------------|------------------|")

            ptab_codes.sort(key=lambda x: x['code'])

            for code_info in ptab_codes:
                output.append(f"| `{code_info['code']}` | {code_info['description']} | {code_info['process']} |")

        # Add FPD codes section if available
        if fpd_codes:
            output.append("")
            output.append("## FPD (Final Petition Decision) Document Codes")
            output.append("")
            output.append("| Code | Description | Business Process |")
            output.append("|------|-------------|------------------|")

            fpd_codes.sort(key=lambda x: x['code'])

            for code_info in fpd_codes:
                output.append(f"| `{code_info['code']}` | {code_info['description']} | {code_info['process']} |")

        # Add common codes reference
        output.append("")
        output.append("## Quick Reference - Most Common Codes")
        output.append("")
        output.append("| Code | Document Type |")
        output.append("|------|---------------|")
        output.append("| `A...` | Amendment/Request for Reconsideration-After Non-Final Rejection |")
        output.append("| `A.PE` | Preliminary Amendment |")
        output.append("| `A.NE` | Response After Final Action |")
        output.append("| `SPEC` | Specification |")
        output.append("| `CLM` | Claims |")
        output.append("| `DRW` | Drawings (black and white line drawings) |")
        output.append("| `N/AP` | Notice of Appeal Filed |")
        output.append("| `AP.B` | Appeal Brief Filed |")
        output.append("| `APRB` | Reply Brief Filed |")
        output.append("| `PA..` | Power of Attorney |")
        output.append("| `IDS` | Information Disclosure Statement |")
        output.append("")
        output.append("---")
        output.append("*This table is generated from the USPTO EFS-Web Document Description List and includes document codes used in patent prosecution, PTAB proceedings, and FPD petitions.*")
        output.append("")
        output.append(f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")

        result = "\n".join(output)
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

    except Exception as e:
        logger.error(f"Error generating document codes table: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "error": True,
                "message": f"Failed to generate document codes table: {str(e)}",
                "guidance": "Check that reference/Document_Descriptions_List.csv exists in project root"
            }
        )

