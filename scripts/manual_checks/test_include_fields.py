#!/usr/bin/env python3
"""
Test script demonstrating the include_fields parameter for XML retrieval

This shows how users can now specify exactly which fields they want from
the XML content, reducing context usage when they only need specific information.
"""

def demonstrate_include_fields_usage():
    """Show example usage patterns for the include_fields parameter"""

    examples = [
        {
            "use_case": "Default (optimized for general patent analysis)",
            "call": "pfw_get_patent_or_application_xml(identifier='7971071')",
            "fields_returned": ["xml_type", "abstract", "claims", "description"],
            "context_size": "~5K tokens"
        },
        {
            "use_case": "Just claims (for claim analysis)",
            "call": "pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['claims'])",
            "fields_returned": ["xml_type", "claims"],
            "context_size": "~2K tokens"
        },
        {
            "use_case": "Claims + citations (for prior art analysis)",
            "call": "pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['claims', 'citations'])",
            "fields_returned": ["xml_type", "claims", "citations"],
            "context_size": "~3K tokens"
        },
        {
            "use_case": "Just inventors (for portfolio analysis)",
            "call": "pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['inventors'])",
            "fields_returned": ["xml_type", "inventors"],
            "context_size": "~500 tokens"
        },
        {
            "use_case": "Everything (maximum context)",
            "call": """pfw_get_patent_or_application_xml(
    identifier='7971071',
    include_fields=['abstract', 'claims', 'description', 'inventors', 'applicants', 'classifications', 'citations', 'publication_info']
)""",
            "fields_returned": ["xml_type", "abstract", "claims", "description", "inventors", "applicants", "classifications", "citations", "publication_info"],
            "context_size": "~29K tokens"
        }
    ]

    print("=" * 80)
    print("XML FIELD SELECTION EXAMPLES")
    print("=" * 80)
    print()

    for i, example in enumerate(examples, 1):
        print(f"{i}. {example['use_case']}")
        print(f"   Call: {example['call']}")
        print(f"   Returns: {', '.join(example['fields_returned'])}")
        print(f"   Context: {example['context_size']}")
        print()

    print("=" * 80)
    print("AVAILABLE FIELDS")
    print("=" * 80)
    print()

    fields = [
        ("abstract", "Full abstract text", "Core content"),
        ("claims", "All independent and dependent claims", "Core content"),
        ("description", "First 5 paragraphs of specification", "Core content"),
        ("inventors", "List of inventors with names and locations", "Metadata"),
        ("applicants", "Applicant information", "Metadata"),
        ("classifications", "USPTO and IPC classifications", "Metadata"),
        ("citations", "Forward and backward citations", "References"),
        ("publication_info", "Publication dates and numbers", "Metadata")
    ]

    for field, description, category in fields:
        print(f"  {field:20} - {description:45} [{category}]")

    print()
    print("=" * 80)
    print("CONTEXT OPTIMIZATION TIPS")
    print("=" * 80)
    print()
    print("1. Default includes core content only (abstract, claims, description)")
    print("2. For metadata, prefer pfw_search_applications_balanced (already in context)")
    print("3. For citations, consider uspto_enriched_citation_mcp (richer data)")
    print("4. Request only what you need to minimize token usage")
    print()

if __name__ == "__main__":
    demonstrate_include_fields_usage()
