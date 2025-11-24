"""
Package management utilities for USPTO Patent File Wrapper MCP

Implements the 3-tier package system:
- Basic: Core patent documents (ABST, DRW, SPEC, CLM)
- Prosecution: Core + key prosecution documents (NOA, Office Actions, Citations)
- Full: Complete prosecution history with smart filtering

Also provides claim evolution tracking and content extraction capabilities.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from ..models.constants import DocumentDirection

logger = logging.getLogger(__name__)


@dataclass
class PackageDocument:
    """Information about a document in a package"""
    document_code: str
    document_description: str
    document_identifier: str
    official_date: str
    page_count: int
    file_size_bytes: int
    download_url: Optional[str] = None
    proxy_url: Optional[str] = None
    category: str = "standard"  # "critical", "important", "standard", "administrative"


@dataclass
class PackageInfo:
    """Complete package information"""
    package_type: str  # "basic", "prosecution", "full"
    application_number: str
    patent_number: Optional[str]
    invention_title: Optional[str]
    documents: List[PackageDocument]
    total_documents: int
    total_pages: int
    estimated_size_mb: float
    package_notes: List[str]
    processing_time_seconds: float


class PackageManager:
    """
    Manages the creation and organization of document packages
    """
    
    # Document importance categories for litigation/analysis
    CRITICAL_DOCS = ["NOA", "CTFR", "CTNF", "CLM", "ABST"]
    IMPORTANT_DOCS = ["892", "1449", "REM", "FWCLM", "DRW", "SPEC"]
    STANDARD_DOCS = ["RCEX", "EXIN", "CTAV", "IDS", "WFEE"]
    
    def __init__(self, api_client, proxy_port: int = 8080):
        self.api_client = api_client
        self.proxy_port = proxy_port
    
    async def create_basic_package(
        self, 
        app_number: str,
        include_drawings: bool = True,
        include_original_claims: bool = False
    ) -> PackageInfo:
        """
        Create basic patent package - core documents only
        
        Documents: ABST, DRW, SPEC, CLM (4 documents)
        Use case: Quick review, portfolio cataloging
        """
        start_time = datetime.now()
        
        try:
            # Use existing tool for basic package
            result = await self.api_client.get_granted_patent_documents_download(
                app_number=app_number,
                include_drawings=include_drawings,
                include_original_claims=include_original_claims
            )
            
            if not result.get('success'):
                raise Exception(f"Failed to get basic package: {result.get('error', 'Unknown error')}")
            
            # Convert to standardized format
            documents = []
            total_pages = 0
            
            for doc_type, doc_info in result.get('document_downloads', {}).items():
                if doc_info and doc_info.get('document_info'):
                    doc = PackageDocument(
                        document_code=doc_info['document_info'].get('document_code', doc_type),
                        document_description=doc_info['document_info'].get('document_description', doc_type),
                        document_identifier=doc_info.get('document_identifier', ''),
                        official_date=doc_info['document_info'].get('official_date', ''),
                        page_count=doc_info['document_info'].get('page_count', 0),
                        file_size_bytes=doc_info['document_info'].get('file_size_bytes', 0),
                        proxy_url=doc_info.get('proxy_download_url'),
                        category="critical" if doc_info['document_info'].get('document_code') in self.CRITICAL_DOCS else "important"
                    )
                    documents.append(doc)
                    total_pages += doc.page_count
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return PackageInfo(
                package_type="basic",
                application_number=app_number,
                patent_number=result.get('patent_number'),
                invention_title=result.get('invention_title'),
                documents=documents,
                total_documents=len(documents),
                total_pages=total_pages,
                estimated_size_mb=total_pages * 0.5,  # Rough estimate
                package_notes=["Core patent documents only", "Fast retrieval (1 API call)"],
                processing_time_seconds=processing_time
            )
            
        except Exception as e:
            logger.error(f"Failed to create basic package for {app_number}: {e}")
            raise
    
    async def create_prosecution_package(
        self, 
        app_number: str,
        include_content_extraction: bool = False
    ) -> PackageInfo:
        """
        Create prosecution package - core + key prosecution documents
        
        Documents: Basic + NOA, Office Actions, Citations, Claims evolution (10-15 docs)
        Use case: Due diligence, licensing, portfolio analysis
        """
        start_time = datetime.now()
        
        try:
            # Start with basic package
            basic_package = await self.create_basic_package(app_number)
            
            # Add prosecution documents with smart filtering
            prosecution_docs = []
            package_notes = list(basic_package.package_notes)
            
            # 1. Notice of Allowance - Critical for understanding examiner reasoning
            try:
                noa_docs = await self.api_client.get_documents(
                    app_number,
                    document_code="NOA",
                    limit=5
                )
                if noa_docs.get('success') and noa_docs.get('documentBag'):
                    for doc in noa_docs['documentBag'][:2]:  # Max 2 NOAs
                        prosecution_docs.append(self._create_package_document(doc, "critical"))
                    package_notes.append(f"Added {len(noa_docs['documentBag'][:2])} Notice(s) of Allowance")
            except Exception as e:
                logger.warning(f"Could not retrieve NOA for {app_number}: {e}")
            
            # 2. Final Rejections - Critical for understanding objections
            try:
                ctfr_docs = await self.api_client.get_documents(
                    app_number,
                    document_code="CTFR",
                    direction_category=DocumentDirection.OUTGOING,
                    limit=3
                )
                if ctfr_docs.get('success') and ctfr_docs.get('documentBag'):
                    for doc in ctfr_docs['documentBag']:
                        prosecution_docs.append(self._create_package_document(doc, "critical"))
                    package_notes.append(f"Added {len(ctfr_docs['documentBag'])} Final Rejection(s)")
            except Exception as e:
                logger.warning(f"Could not retrieve CTFR for {app_number}: {e}")
            
            # 3. Non-Final Rejections - Important for prosecution history
            try:
                ctnf_docs = await self.api_client.get_documents(
                    app_number,
                    document_code="CTNF",
                    direction_category=DocumentDirection.OUTGOING,
                    limit=2
                )
                if ctnf_docs.get('success') and ctnf_docs.get('documentBag'):
                    for doc in ctnf_docs['documentBag']:
                        prosecution_docs.append(self._create_package_document(doc, "important"))
                    package_notes.append(f"Added {len(ctnf_docs['documentBag'])} Non-Final Rejection(s)")
            except Exception as e:
                logger.warning(f"Could not retrieve CTNF for {app_number}: {e}")
            
            # 4. Examiner Citations - Important for prior art analysis
            try:
                examiner_cites = await self.api_client.get_documents(
                    app_number,
                    document_code="892",
                    limit=5
                )
                if examiner_cites.get('success') and examiner_cites.get('documentBag'):
                    for doc in examiner_cites['documentBag']:
                        prosecution_docs.append(self._create_package_document(doc, "important"))
                    package_notes.append(f"Added {len(examiner_cites['documentBag'])} Examiner Citation(s)")
            except Exception as e:
                logger.warning(f"Could not retrieve examiner citations for {app_number}: {e}")
            
            # 5. Applicant Citations - Important for understanding disclosed prior art
            try:
                applicant_cites = await self.api_client.get_documents(
                    app_number,
                    document_code="1449",
                    limit=5
                )
                if applicant_cites.get('success') and applicant_cites.get('documentBag'):
                    for doc in applicant_cites['documentBag']:
                        prosecution_docs.append(self._create_package_document(doc, "important"))
                    package_notes.append(f"Added {len(applicant_cites['documentBag'])} Applicant Citation(s)")
            except Exception as e:
                logger.warning(f"Could not retrieve applicant citations for {app_number}: {e}")
            
            # 6. Applicant Remarks - Important for understanding arguments
            try:
                remarks = await self.api_client.get_documents(
                    app_number,
                    document_code="REM",
                    direction_category=DocumentDirection.INCOMING,
                    limit=3
                )
                if remarks.get('success') and remarks.get('documentBag'):
                    for doc in remarks['documentBag']:
                        prosecution_docs.append(self._create_package_document(doc, "important"))
                    package_notes.append(f"Added {len(remarks['documentBag'])} Applicant Remark(s)")
            except Exception as e:
                logger.warning(f"Could not retrieve remarks for {app_number}: {e}")
            
            # Combine all documents
            all_documents = basic_package.documents + prosecution_docs
            total_pages = sum(doc.page_count for doc in all_documents)
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return PackageInfo(
                package_type="prosecution",
                application_number=app_number,
                patent_number=basic_package.patent_number,
                invention_title=basic_package.invention_title,
                documents=all_documents,
                total_documents=len(all_documents),
                total_pages=total_pages,
                estimated_size_mb=total_pages * 0.5,
                package_notes=package_notes,
                processing_time_seconds=processing_time
            )
            
        except Exception as e:
            logger.error(f"Failed to create prosecution package for {app_number}: {e}")
            raise
    
    async def create_full_package(self, app_number: str) -> PackageInfo:
        """
        Create full litigation package - complete prosecution history
        
        Documents: Prosecution + RCE, Interviews, Affidavits, etc. (20-40 docs)
        Use case: Deep litigation research, expert witness prep
        """
        start_time = datetime.now()
        
        try:
            # Start with prosecution package
            prosecution_package = await self.create_prosecution_package(app_number)
            
            # Get ALL documents and categorize
            all_docs_result = await self.api_client.get_documents(app_number, limit=200)
            
            if not all_docs_result.get('success'):
                # Return prosecution package if we can't get more
                return prosecution_package
            
            all_docs = all_docs_result.get('documentBag', [])
            
            # Filter out documents we already have
            existing_identifiers = {doc.document_identifier for doc in prosecution_package.documents}
            new_docs = [doc for doc in all_docs if doc.get('documentIdentifier') not in existing_identifiers]
            
            # Categorize and prioritize additional documents
            additional_docs = []
            for doc in new_docs:
                doc_code = doc.get('documentCode', '')
                category = self._categorize_document(doc_code)
                
                # Only include medium priority and above for full package
                if category in ["critical", "important", "standard"]:
                    additional_docs.append(self._create_package_document(doc, category))
            
            # Sort by category and date
            additional_docs.sort(key=lambda x: (
                {"critical": 0, "important": 1, "standard": 2}.get(x.category, 3),
                x.official_date
            ))
            
            # Combine all documents
            all_documents = prosecution_package.documents + additional_docs
            total_pages = sum(doc.page_count for doc in all_documents)
            
            package_notes = list(prosecution_package.package_notes)
            package_notes.append(f"Added {len(additional_docs)} additional prosecution documents")
            package_notes.append("Complete prosecution history included")
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return PackageInfo(
                package_type="full",
                application_number=app_number,
                patent_number=prosecution_package.patent_number,
                invention_title=prosecution_package.invention_title,
                documents=all_documents,
                total_documents=len(all_documents),
                total_pages=total_pages,
                estimated_size_mb=total_pages * 0.5,
                package_notes=package_notes,
                processing_time_seconds=processing_time
            )
            
        except Exception as e:
            logger.error(f"Failed to create full package for {app_number}: {e}")
            raise
    
    def _create_package_document(self, doc_data: Dict[str, Any], category: str) -> PackageDocument:
        """Convert API document data to PackageDocument"""
        download_options = doc_data.get('downloadOptionBag', [])
        pdf_option = next((opt for opt in download_options if opt.get('mimeTypeIdentifier') == 'PDF'), None)
        
        doc_id = doc_data.get('documentIdentifier', '')
        proxy_url = f"http://localhost:{self.proxy_port}/download/{doc_data.get('applicationNumber', '')}/{doc_id}" if doc_id else None
        
        return PackageDocument(
            document_code=doc_data.get('documentCode', ''),
            document_description=doc_data.get('documentCodeDescriptionText', ''),
            document_identifier=doc_id,
            official_date=doc_data.get('officialDate', ''),
            page_count=pdf_option.get('pageTotalQuantity', 0) if pdf_option else 0,
            file_size_bytes=pdf_option.get('fileSizeQuantity', 0) if pdf_option else 0,
            download_url=pdf_option.get('downloadUrl') if pdf_option else None,
            proxy_url=proxy_url,
            category=category
        )
    
    def _categorize_document(self, doc_code: str) -> str:
        """Categorize document by litigation/analysis importance"""
        if doc_code in self.CRITICAL_DOCS:
            return "critical"
        elif doc_code in self.IMPORTANT_DOCS:
            return "important"
        elif doc_code in self.STANDARD_DOCS:
            return "standard"
        else:
            return "administrative"


async def get_claim_evolution(api_client, app_number: str) -> Dict[str, Any]:
    """
    Track claim evolution from filing to grant
    
    Returns:
        {
            "original_claims": {...},
            "final_claims": {...},
            "intermediate_amendments": [...],
            "amendment_count": int,
            "prosecution_complexity": str
        }
    """
    try:
        # Get ALL claim documents
        claims_result = await api_client.get_documents(
            app_number,
            document_code="CLM",
            limit=50
        )
        
        if not claims_result.get('success') or not claims_result.get('documentBag'):
            return {
                "error": "No claim documents found",
                "amendment_count": 0,
                "prosecution_complexity": "unknown"
            }
        
        claims_docs = claims_result['documentBag']
        
        # Sort by official date
        sorted_claims = sorted(claims_docs, key=lambda x: x.get('officialDate', ''))
        
        if len(sorted_claims) < 2:
            return {
                "original_claims": sorted_claims[0] if sorted_claims else None,
                "final_claims": sorted_claims[0] if sorted_claims else None,
                "intermediate_amendments": [],
                "amendment_count": 0,
                "prosecution_complexity": "minimal"
            }
        
        # Determine complexity
        amendment_count = len(sorted_claims) - 1
        if amendment_count == 0:
            complexity = "minimal"
        elif amendment_count <= 2:
            complexity = "standard"
        elif amendment_count <= 5:
            complexity = "moderate"
        else:
            complexity = "high"
        
        return {
            "original_claims": sorted_claims[0],
            "final_claims": sorted_claims[-1],
            "intermediate_amendments": sorted_claims[1:-1],
            "amendment_count": amendment_count,
            "prosecution_complexity": complexity,
            "total_claim_documents": len(sorted_claims),
            "date_range": {
                "first": sorted_claims[0].get('officialDate'),
                "last": sorted_claims[-1].get('officialDate')
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get claim evolution for {app_number}: {e}")
        return {
            "error": str(e),
            "amendment_count": 0,
            "prosecution_complexity": "unknown"
        }


def format_package_summary(package_info: PackageInfo) -> str:
    """
    Generate a formatted summary of the package for user presentation
    """
    summary = f"""
# {package_info.package_type.title()} Patent Package

**Application:** {package_info.application_number}
**Patent:** {package_info.patent_number or "Not granted"}
**Title:** {package_info.invention_title or "Not available"}

## Package Contents
- **Total Documents:** {package_info.total_documents}
- **Total Pages:** {package_info.total_pages}
- **Estimated Size:** {package_info.estimated_size_mb:.1f} MB
- **Processing Time:** {package_info.processing_time_seconds:.1f} seconds

## Document Breakdown by Category
"""
    
    # Group documents by category
    by_category = {}
    for doc in package_info.documents:
        category = doc.category
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(doc)
    
    for category in ["critical", "important", "standard", "administrative"]:
        if category in by_category:
            docs = by_category[category]
            summary += f"\n### {category.title()} Documents ({len(docs)})\n"
            for doc in docs:
                summary += f"- **{doc.document_code}**: {doc.document_description} ({doc.page_count} pages)\n"
    
    # Add package notes
    if package_info.package_notes:
        summary += "\n## Package Notes\n"
        for note in package_info.package_notes:
            summary += f"- {note}\n"
    
    return summary