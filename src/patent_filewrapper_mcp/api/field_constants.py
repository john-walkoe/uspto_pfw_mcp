"""
USPTO Patent File Wrapper API Field Constants

This module defines all USPTO API field names as constants to eliminate
magic strings throughout the codebase and provide a single source of truth.
"""


class USPTOFields:
    """
    Constants for USPTO Patent File Wrapper API field names.

    These constants represent the exact field names used by the USPTO API.
    Use these instead of hardcoded strings to enable:
    - IDE autocomplete
    - Easier refactoring
    - Catching typos at development time
    """

    # Top-level fields
    APPLICATION_NUMBER_TEXT = "applicationNumberText"
    PARENT_CONTINUITY_BAG = "parentContinuityBag"
    CHILD_CONTINUITY_BAG = "childContinuityBag"
    DOCUMENT_BAG = "documentBag"
    ASSOCIATED_DOCUMENTS = "associatedDocuments"

    # ApplicationMetaData fields (commonly accessed)
    INVENTION_TITLE = "applicationMetaData.inventionTitle"
    PATENT_NUMBER = "applicationMetaData.patentNumber"
    FILING_DATE = "applicationMetaData.filingDate"
    GRANT_DATE = "applicationMetaData.grantDate"
    APPLICATION_STATUS_DESCRIPTION_TEXT = "applicationMetaData.applicationStatusDescriptionText"
    APPLICATION_STATUS_CODE = "applicationMetaData.applicationStatusCode"
    APPLICATION_STATUS_DATE = "applicationMetaData.applicationStatusDate"

    # Inventor fields
    FIRST_INVENTOR_NAME = "applicationMetaData.firstInventorName"
    INVENTOR_BAG = "applicationMetaData.inventorBag"
    INVENTOR_NAME_TEXT = "applicationMetaData.inventorBag.inventorNameText"

    # Applicant fields
    FIRST_APPLICANT_NAME = "applicationMetaData.firstApplicantName"
    APPLICANT_BAG = "applicationMetaData.applicantBag"
    APPLICANT_NAME_TEXT = "applicationMetaData.applicantBag.applicantNameText"

    # Assignee fields
    ASSIGNEE_BAG = "applicationMetaData.assigneeBag"

    # Examiner and Art Unit fields
    EXAMINER_NAME_TEXT = "applicationMetaData.examinerNameText"
    GROUP_ART_UNIT_NUMBER = "applicationMetaData.groupArtUnitNumber"

    # Administrative fields
    CUSTOMER_NUMBER = "applicationMetaData.customerNumber"
    DOCKET_NUMBER = "applicationMetaData.docketNumber"
    APPLICATION_CONFIRMATION_NUMBER = "applicationMetaData.applicationConfirmationNumber"

    # Entity status
    ENTITY_STATUS_DATA = "applicationMetaData.entityStatusData"

    # Classification fields
    USPC_SYMBOL_TEXT = "applicationMetaData.uspcSymbolText"
    CPC_CLASSIFICATION_BAG = "applicationMetaData.cpcClassificationBag"
    CLASS = "applicationMetaData.class"
    SUBCLASS = "applicationMetaData.subclass"

    # Application type fields
    APPLICATION_TYPE_CODE = "applicationMetaData.applicationTypeCode"
    APPLICATION_TYPE_LABEL_NAME = "applicationMetaData.applicationTypeLabelName"
    APPLICATION_TYPE_CATEGORY = "applicationMetaData.applicationTypeCategory"

    # Publication fields
    EARLIEST_PUBLICATION_NUMBER = "applicationMetaData.earliestPublicationNumber"
    EARLIEST_PUBLICATION_DATE = "applicationMetaData.earliestPublicationDate"
    PUBLICATION_DATE_BAG = "applicationMetaData.publicationDateBag"
    PUBLICATION_SEQUENCE_NUMBER_BAG = "applicationMetaData.publicationSequenceNumberBag"
    PUBLICATION_CATEGORY_BAG = "applicationMetaData.publicationCategoryBag"

    # Filing date fields
    EFFECTIVE_FILING_DATE = "applicationMetaData.effectiveFilingDate"

    # PCT fields
    PCT_PUBLICATION_NUMBER = "applicationMetaData.pctPublicationNumber"
    PCT_PUBLICATION_DATE = "applicationMetaData.pctPublicationDate"
    NATIONAL_STAGE_INDICATOR = "applicationMetaData.nationalStageIndicator"

    # International registration fields
    INTERNATIONAL_REGISTRATION_NUMBER = "applicationMetaData.internationalRegistrationNumber"
    INTERNATIONAL_REGISTRATION_PUBLICATION_DATE = "applicationMetaData.internationalRegistrationPublicationDate"

    # First inventor to file indicator
    FIRST_INVENTOR_TO_FILE_INDICATOR = "applicationMetaData.firstInventorToFileIndicator"

    # Parent continuity fields (nested)
    PARENT_PATENT_NUMBER = "parentContinuityBag.parentPatentNumber"
    PARENT_APPLICATION_NUMBER_TEXT = "parentContinuityBag.parentApplicationNumberText"

    # Child continuity fields (nested)
    CHILD_APPLICATION_NUMBER_TEXT = "childContinuityBag.childApplicationNumberText"


# Convenience mappings for query building
class QueryFieldNames:
    """
    Field names as they appear in Lucene queries (without 'applicationMetaData.' prefix where applicable).

    Use these for building search queries with convenience parameters.
    """
    ART_UNIT = "applicationMetaData.groupArtUnitNumber"
    EXAMINER_NAME = "applicationMetaData.examinerNameText"
    APPLICANT_NAME = "applicationMetaData.applicantBag.applicantNameText"
    INVENTOR_NAME = "applicationMetaData.inventorBag.inventorNameText"
    CUSTOMER_NUMBER = "applicationMetaData.customerNumber"
    STATUS_CODE = "applicationMetaData.applicationStatusCode"
    FILING_DATE = "applicationMetaData.filingDate"
    GRANT_DATE = "applicationMetaData.grantDate"
    PATENT_NUMBER = "applicationMetaData.patentNumber"
    PARENT_PATENT_NUMBER = "parentPatentNumber"
