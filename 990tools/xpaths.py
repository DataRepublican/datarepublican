#!/usr/bin/env python3
"""
xpaths.py - Unified XPath configuration for all IRS 990 form types

This module consolidates XPath expressions for Forms 990, 990EZ, and 990PF
into a single, unified configuration to reduce duplication and improve maintainability.
"""

from lxml import etree  # type: ignore

# Export tostring for convenience
tostring = etree.tostring

# Common namespaces used across all forms
NAMESPACES = {'irs': 'http://www.irs.gov/efile'}

# Common XPath patterns shared across forms
COMMON_XPATHS = {
    "form_type": [
        etree.XPath(".//irs:ReturnHeader/irs:ReturnTypeCd", namespaces=NAMESPACES),
        etree.XPath(".//ReturnHeader/ReturnTypeCd", namespaces=NAMESPACES),
    ],
    "tax_year": [
        etree.XPath(".//irs:ReturnHeader/irs:TaxYr", namespaces=NAMESPACES),
        etree.XPath(".//ReturnHeader/TaxYr", namespaces=NAMESPACES),
    ],
    "filer_ein": [
        etree.XPath(".//irs:Filer/irs:EIN", namespaces=NAMESPACES),
        etree.XPath(".//Filer/EIN", namespaces=NAMESPACES),
    ],
    "filer_name": [
        etree.XPath(".//irs:Filer/irs:BusinessName/irs:BusinessNameLine1Txt", namespaces=NAMESPACES),
        etree.XPath(".//Filer/BusinessName/BusinessNameLine1Txt", namespaces=NAMESPACES),
    ],
    "business_name_line1": [
        etree.XPath(".//irs:Filer/irs:BusinessName/irs:BusinessNameLine1Txt", namespaces=NAMESPACES),
        etree.XPath(".//Filer/BusinessName/BusinessNameLine1Txt", namespaces=NAMESPACES),
    ],
    "business_name_line2": [
        etree.XPath(".//irs:Filer/irs:BusinessName/irs:BusinessNameLine2Txt", namespaces=NAMESPACES),
        etree.XPath(".//Filer/BusinessName/BusinessNameLine2Txt", namespaces=NAMESPACES),
    ],
    "return_data": [
        etree.XPath(".//irs:ReturnData", namespaces=NAMESPACES),
        etree.XPath(".//ReturnData", namespaces=NAMESPACES),
    ],
    "address_line1": [
        etree.XPath(".//irs:Filer/irs:USAddress/irs:AddressLine1Txt", namespaces=NAMESPACES),
        etree.XPath(".//Filer/USAddress/AddressLine1Txt", namespaces=NAMESPACES),
    ],
    "address_line2": [
        etree.XPath(".//irs:Filer/irs:USAddress/irs:AddressLine2Txt", namespaces=NAMESPACES),
        etree.XPath(".//Filer/USAddress/AddressLine2Txt", namespaces=NAMESPACES),
    ],
    "city": [
        etree.XPath(".//irs:Filer/irs:USAddress/irs:CityNm", namespaces=NAMESPACES),
        etree.XPath(".//Filer/USAddress/CityNm", namespaces=NAMESPACES),
    ],
    "state": [
        etree.XPath(".//irs:Filer/irs:USAddress/irs:StateAbbreviationCd", namespaces=NAMESPACES),
        etree.XPath(".//Filer/USAddress/StateAbbreviationCd", namespaces=NAMESPACES),
    ],
    "zip_code": [
        etree.XPath(".//irs:Filer/irs:USAddress/irs:ZIPCd", namespaces=NAMESPACES),
        etree.XPath(".//Filer/USAddress/ZIPCd", namespaces=NAMESPACES),
    ],
    "recipient_address_line1": [
        etree.XPath(".//irs:RecipientUSAddress/irs:AddressLine1Txt", namespaces=NAMESPACES),
        etree.XPath(".//RecipientUSAddress/AddressLine1Txt", namespaces=NAMESPACES),
        etree.XPath(".//irs:RecipientForeignAddress/irs:AddressLine1Txt", namespaces=NAMESPACES),
        etree.XPath(".//RecipientForeignAddress/AddressLine1Txt", namespaces=NAMESPACES),
    ],
    "recipient_address_line2": [
        etree.XPath(".//irs:RecipientUSAddress/irs:AddressLine2Txt", namespaces=NAMESPACES),
        etree.XPath(".//RecipientUSAddress/AddressLine2Txt", namespaces=NAMESPACES),
        etree.XPath(".//irs:RecipientForeignAddress/irs:AddressLine2Txt", namespaces=NAMESPACES),
        etree.XPath(".//RecipientForeignAddress/AddressLine2Txt", namespaces=NAMESPACES),
    ],
    "recipient_city": [
        etree.XPath(".//irs:RecipientUSAddress/irs:CityNm", namespaces=NAMESPACES),
        etree.XPath(".//RecipientUSAddress/CityNm", namespaces=NAMESPACES),
        etree.XPath(".//irs:RecipientForeignAddress/irs:CityNm", namespaces=NAMESPACES),
        etree.XPath(".//RecipientForeignAddress/CityNm", namespaces=NAMESPACES),
    ],
    "recipient_state": [
        etree.XPath(".//irs:RecipientUSAddress/irs:StateAbbreviationCd", namespaces=NAMESPACES),
        etree.XPath(".//RecipientUSAddress/StateAbbreviationCd", namespaces=NAMESPACES),
        etree.XPath(".//irs:RecipientForeignAddress/irs:StateAbbreviationCd", namespaces=NAMESPACES),
        etree.XPath(".//RecipientForeignAddress/StateAbbreviationCd", namespaces=NAMESPACES),
    ],
    "recipient_zip_code": [
        etree.XPath(".//irs:RecipientUSAddress/irs:ZIPCd", namespaces=NAMESPACES),
        etree.XPath(".//RecipientUSAddress/ZIPCd", namespaces=NAMESPACES),
        etree.XPath(".//irs:RecipientForeignAddress/irs:ZIPCd", namespaces=NAMESPACES),
        etree.XPath(".//RecipientForeignAddress/ZIPCd", namespaces=NAMESPACES),
    ],
    # Common officer compensation patterns
    "officer_comp_value": [
        etree.XPath("irs:ReportableCompFromOrgAmt", namespaces=NAMESPACES),
        etree.XPath("ReportableCompFromOrgAmt", namespaces=NAMESPACES),
        etree.XPath("irs:CompensationAmt", namespaces=NAMESPACES),
        etree.XPath("CompensationAmt", namespaces=NAMESPACES),
    ],
    "officer_name": [
        etree.XPath("irs:PersonNm", namespaces=NAMESPACES),
        etree.XPath("PersonNm", namespaces=NAMESPACES),
    ],
    # Common grant patterns
    "grant_value": [
        etree.XPath("irs:CashGrantAmt", namespaces=NAMESPACES),
    ],
    # Common foreign expense patterns
    "foreign_exp_value": [
        etree.XPath("irs:RegionTotalExpendituresAmt", namespaces=NAMESPACES),
    ],
    # Common schedule O patterns
    "schedule_o_value": [
        etree.XPath(".//irs:ExplanationTxt", namespaces=NAMESPACES),
        etree.XPath(".//irs:SupplementalInformationDetail/irs:ExplanationTxt", namespaces=NAMESPACES),
        etree.XPath(".//irs:Form990ScheduleO/irs:Explanation", namespaces=NAMESPACES),
    ],
    # Filer address components
    "filer_address_line1": [
        etree.XPath(".//ReturnHeader/Filer/USAddress/AddressLine1Txt"),
        etree.XPath(".//Filer/USAddress/AddressLine1Txt"),
        etree.XPath(".//USAddress/AddressLine1Txt"),
    ],
    "filer_address_line2": [
        etree.XPath(".//ReturnHeader/Filer/USAddress/AddressLine2Txt"),
        etree.XPath(".//Filer/USAddress/AddressLine2Txt"),
        etree.XPath(".//USAddress/AddressLine2Txt"),
    ],
    "filer_city": [
        etree.XPath(".//ReturnHeader/Filer/USAddress/CityNm"),
        etree.XPath(".//Filer/USAddress/CityNm"),
        etree.XPath(".//USAddress/CityNm"),
    ],
    "filer_state": [
        etree.XPath(".//ReturnHeader/Filer/USAddress/StateAbbreviationCd"),
        etree.XPath(".//Filer/USAddress/StateAbbreviationCd"),
        etree.XPath(".//USAddress/StateAbbreviationCd"),
    ],
    "filer_zip_code": [
        etree.XPath(".//ReturnHeader/Filer/USAddress/ZIPCd"),
        etree.XPath(".//Filer/USAddress/ZIPCd"),
        etree.XPath(".//USAddress/ZIPCd"),
    ],
    "filer_name_xpaths": [
        etree.XPath(".//irs:ReturnHeader/irs:Filer/irs:BusinessName/irs:BusinessNameLine1Txt", namespaces=NAMESPACES),
        etree.XPath(".//ReturnHeader/Filer/BusinessName/BusinessNameLine1Txt"),
        etree.XPath(".//irs:ReturnHeader/irs:Filer/irs:Name/irs:BusinessNameLine1Txt", namespaces=NAMESPACES),
        etree.XPath(".//ReturnHeader/Filer/Name/BusinessNameLine1Txt")
    ],
    # Political contribution components
    "political_recipient_name": [
        etree.XPath(".//irs:RecipientNm", namespaces=NAMESPACES),
        etree.XPath(".//irs:RecipientName", namespaces=NAMESPACES),
        etree.XPath(".//RecipientNm"),
        etree.XPath(".//RecipientName"),
        etree.XPath("irs:RecipientNm", namespaces=NAMESPACES),
        etree.XPath("irs:RecipientName", namespaces=NAMESPACES),
        etree.XPath("RecipientNm"),
        etree.XPath("RecipientName"),
    ],
    "political_amount": [
        etree.XPath(".//irs:TotalDirectExpendAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:Amount", namespaces=NAMESPACES),
        etree.XPath(".//TotalDirectExpendAmt"),
        etree.XPath(".//Amount"),
        etree.XPath("irs:TotalDirectExpendAmt", namespaces=NAMESPACES),
        etree.XPath("irs:Amount", namespaces=NAMESPACES),
        etree.XPath("TotalDirectExpendAmt"),
        etree.XPath("Amount"),
    ],
    "political_ein": [
        etree.XPath(".//irs:EIN", namespaces=NAMESPACES),
        etree.XPath(".//irs:RecipientEIN", namespaces=NAMESPACES),
        etree.XPath(".//EIN"),
        etree.XPath(".//RecipientEIN"),
        etree.XPath("irs:EIN", namespaces=NAMESPACES),
        etree.XPath("irs:RecipientEIN", namespaces=NAMESPACES),
        etree.XPath("EIN"),
        etree.XPath("RecipientEIN"),
    ],
}

# Form-specific XPath configurations
# Import form-specific XPath configurations
try:
    from xpaths_990 import XPATHS_990
    from xpaths_990ez import XPATHS_990EZ
    from xpaths_990pf import XPATHS_990PF
except ImportError:
    # Fallback for direct execution
    from xpaths_990 import XPATHS_990
    from xpaths_990ez import XPATHS_990EZ
    from xpaths_990pf import XPATHS_990PF

# Grant-related XPath patterns
GRANT_XPATHS = {
    "990": [
        etree.XPath(".//irs:IRS990ScheduleI/irs:RecipientTable", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleF/irs:GrantsToOrgOutsideUSGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleF/irs:GrantsToOrganizationsOutsideUS", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleF/irs:GrantsToOrgsOutsideUS", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleF/irs:ForeignIndividualsGrantsGrp", namespaces=NAMESPACES),
    ],
    "990EZ": [
        etree.XPath(".//irs:IRS990ScheduleI/irs:RecipientTable", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleF/irs:GrantsToOrgOutsideUSGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleF/irs:GrantsToOrganizationsOutsideUS", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleF/irs:GrantsToOrgsOutsideUS", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleF/irs:ForeignIndividualsGrantsGrp", namespaces=NAMESPACES),
    ],
    "990PF": [
        etree.XPath(".//irs:IRS990PF/irs:SupplementaryInformationGrp", namespaces=NAMESPACES),
    ],
}

GRANT_EIN_XPATHS = [
    etree.XPath("irs:RecipientEIN", namespaces=NAMESPACES),
    etree.XPath("irs:EIN", namespaces=NAMESPACES),
]
GRANT_UNION_EIN_XPATHS = etree.XPath("irs:RecipientEIN | irs:EIN", namespaces=NAMESPACES)
    

GRANT_NAME_XPATHS = [
    etree.XPath("irs:RecipientNameBusiness | irs:RecipientBusinessName/irs:BusinessNameLine1Txt | irs:BusinessName/irs:BusinessNameLine1Txt", namespaces=NAMESPACES),
]

GRANT_AMOUNT_XPATHS = [
    etree.XPath("irs:CashGrantAmt | irs:TotalGrantOrContriPdDurYrAmt | irs:GrantOrContributionAmt | irs:Amount", namespaces=NAMESPACES),
]

GRANT_FOREIGN_ADDRESS_XPATH = etree.XPath("irs:ForeignAddress", namespaces=NAMESPACES)
GRANT_COUNTRY_XPATH = etree.XPath("irs:CountryCd", namespaces=NAMESPACES)
GRANT_US_ADDRESS_XPATH = etree.XPath("irs:USAddress", namespaces=NAMESPACES)

# Union XPath for grant elements (combines all grant XPath patterns)
GRANT_UNION_XPATH = etree.XPath("""
    .//irs:IRS990ScheduleI/irs:RecipientTable |
    .//irs:IRS990ScheduleF/irs:GrantsToOrgOutsideUSGrp |
    .//irs:IRS990ScheduleF/irs:GrantsToOrganizationsOutsideUS |
    .//irs:IRS990ScheduleF/irs:GrantsToOrgsOutsideUS |
    .//irs:IRS990ScheduleF/irs:ForeignIndividualsGrantsGrp |
    .//irs:IRS990PF/irs:SupplementaryInformationGrp
""", namespaces=NAMESPACES)

# Union XPath for grant names within grant elements
GRANT_NAME_UNION_XPATH = etree.XPath("""
    irs:RecipientNameBusiness |
    irs:RecipientBusinessName/irs:BusinessNameLine1Txt |
    irs:BusinessName/irs:BusinessNameLine1Txt
""", namespaces=NAMESPACES)

# Union XPath for grant amounts within grant elements
GRANT_AMOUNT_UNION_XPATH = etree.XPath("""
    irs:CashGrantAmt |
    irs:TotalGrantOrContriPdDurYrAmt |
    irs:GrantOrContributionAmt |
    irs:Amount
""", namespaces=NAMESPACES)

# Schedule C (Political Contributions) XPath patterns
SCHEDULE_C_XPATHS = {
    "990": [
        etree.XPath(".//irs:IRS990ScheduleC/irs:PoliticalCampaignActyGrp", namespaces=NAMESPACES),
    ],
    "990EZ": [
        etree.XPath(".//irs:IRS990ScheduleC/irs:PoliticalCampaignActyGrp", namespaces=NAMESPACES),
    ],
    "990PF": [
        etree.XPath(".//irs:IRS990ScheduleC/irs:PoliticalCampaignActyGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleC/irs:Section527PoliticalOrgGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleC/irs:NoncharitableExemptOrgSchGrp[irs:ExemptOrganizationTypeCd='527']", namespaces=NAMESPACES),
    ],
}

SCHEDULE_C_AMOUNT_XPATHS = [
    etree.XPath("irs:PoliticalExpendituresAmt", namespaces=NAMESPACES),
    etree.XPath("irs:Amount", namespaces=NAMESPACES),
]

SCHEDULE_C_RECIPIENT_XPATHS = [
    etree.XPath("irs:RecipientNm", namespaces=NAMESPACES),
    etree.XPath("irs:RecipientName", namespaces=NAMESPACES),
]

SCHEDULE_C_EIN_XPATHS = [
    etree.XPath("irs:EIN", namespaces=NAMESPACES),
    etree.XPath("irs:RecipientEIN", namespaces=NAMESPACES),
]

# Schedule L (Contractors) XPath patterns
SCHEDULE_L_XPATHS = {
    "990": [
        etree.XPath(".//irs:IRS990ScheduleL/irs:TransactionsWithInterestedPersonsGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleL/irs:LoansToFromOfficersGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleL/irs:BusinessTransactionsGrp", namespaces=NAMESPACES),
    ],
    "990EZ": [
        etree.XPath(".//irs:IRS990ScheduleL/irs:TransactionsWithInterestedPersonsGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleL/irs:LoansToFromOfficersGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleL/irs:BusinessTransactionsGrp", namespaces=NAMESPACES),
    ],
    "990PF": [
        etree.XPath(".//irs:IRS990ScheduleL/irs:TransactionsWithInterestedPersonsGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleL/irs:LoansToFromOfficersGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990ScheduleL/irs:BusinessTransactionsGrp", namespaces=NAMESPACES),
    ],
}

# Union XPath patterns for optimized parsing (moved from base_parser.py)
CONFERENCES_UNION_XPATH = etree.XPath("""
    .//irs:IRS990/irs:ConferencesMeetingsGrp/irs:TotalAmt |
    .//irs:IRS990EZ/irs:ConferencesMeetingsGrp/irs:TotalAmt |
    .//ConferencesMeetingsGrp/TotalAmt |
    .//irs:ConferencesMeetings/irs:TotalAmt |
    .//ConferencesMeetings/TotalAmt
""", namespaces=NAMESPACES)

RECEIPT_UNION_XPATH = etree.XPath("""
    .//irs:TotalRevenueAmt |
    .//irs:IRS990EZ/irs:TotalRevenueAmt |
    .//irs:IRS990PF/irs:AnalysisOfRevenueAndExpenses/irs:TotalRevenueRevAndExpnssAmt |
    .//irs:AnalysisOfRevenueAndExpenses/irs:TotalRevenueRevAndExpnssAmt |
    .//TotalRevenueAmt
""", namespaces=NAMESPACES)

TOTAL_EXP_UNION_XPATH = etree.XPath("""
    .//irs:IRS990/irs:TotalFunctionalExpensesGrp/irs:TotalAmt |
    .//irs:IRS990/irs:TotalExpensesAmt |
    .//irs:IRS990EZ/irs:TotalExpensesAmt |
    .//irs:IRS990PF/irs:AnalysisOfRevenueAndExpenses/irs:TotalExpensesRevAndExpnssAmt |
    .//irs:AnalysisOfRevenueAndExpenses/irs:TotalExpensesRevAndExpnssAmt |
    .//TotalFunctionalExpensesGrp/TotalAmt |
    .//TotalExpensesAmt
""", namespaces=NAMESPACES)

PROG_EXP_UNION_XPATH = etree.XPath("""
    .//irs:IRS990/irs:TotalProgramServiceExpensesAmt |
    .//irs:IRS990EZ/irs:TotalProgramServiceExpensesAmt |
    .//irs:ProgramServiceExpensesAmt |
    .//TotalProgramServiceExpensesAmt
""", namespaces=NAMESPACES)

TOTAL_ASSETS_UNION_XPATH = etree.XPath("""
    .//irs:IRS990/irs:TotalAssetsEOYAmt |
    .//irs:IRS990EZ/irs:TotalAssetsEOYAmt |
    .//irs:IRS990PF/irs:Form990PFBalanceSheetsGrp/irs:TotalAssetsEOYAmt |
    .//irs:Form990PFBalanceSheetsGrp/irs:TotalAssetsEOYAmt |
    .//TotalAssetsEOYAmt
""", namespaces=NAMESPACES)

FOREIGN_OFFICE_UNION_XPATH = etree.XPath("""
    .//irs:IRS990/irs:ForeignOfficeInd |
    .//irs:IRS990EZ/irs:ForeignOfficeInd |
    .//irs:IRS990EZ/irs:ForeignOfficeCountryCd |
    .//ForeignOfficeInd |
    .//ForeignOfficeCountryCd
""", namespaces=NAMESPACES)


# Contractor parsing union XPaths (moved from base_parser.py)
CONTRACTOR_UNION_XPATH = etree.XPath("""
    .//irs:ReturnData/irs:IRS990/irs:ContractorCompensationGrp |
    .//irs:IRS990/irs:ContractorCompensationGrp |
    .//irs:ReturnData/irs:IRS990EZ/irs:ContractorCompensationGrp |
    .//irs:IRS990EZ/irs:ContractorCompensationGrp |
    .//irs:ReturnData/irs:IRS990PF/irs:CompensationOfHghstPdCntrctGrp |
    .//irs:IRS990PF/irs:CompensationOfHghstPdCntrctGrp |
    .//irs:ContractorCompensationGrp |
    .//irs:CompensationOfHghstPdCntrctGrp
""", namespaces=NAMESPACES)

CONTRACTOR_NAME_UNION_XPATH = etree.XPath("""
    irs:ContractorName/irs:BusinessName/irs:BusinessNameLine1Txt |
    irs:ContractorName/irs:BusinessNameLine1Txt |
    irs:BusinessName/irs:BusinessNameLine1Txt |
    irs:BusinessName/irs:BusinessNameLine1 |
    ContractorName/BusinessName/BusinessNameLine1Txt |
    ContractorName/BusinessNameLine1Txt |
    BusinessName/BusinessNameLine1Txt |
    BusinessName/BusinessNameLine1
""", namespaces=NAMESPACES)

CONTRACTOR_COMP_UNION_XPATH = etree.XPath("""
    irs:ContractorCompensationAmt |
    irs:CompensationAmt |
    ContractorCompensationAmt |
    CompensationAmt
""", namespaces=NAMESPACES)

# Address parsing union XPath (moved from base_parser.py)
ADDRESS_UNION_XPATH = etree.XPath("""
    .//irs:Filer/irs:USAddress/irs:AddressLine1Txt |
    .//irs:Filer/irs:USAddress/irs:AddressLine2Txt |
    .//irs:Filer/irs:USAddress/irs:CityNm |
    .//irs:Filer/irs:USAddress/irs:StateAbbreviationCd |
    .//irs:Filer/irs:USAddress/irs:ZIPCd |
    .//Filer/USAddress/AddressLine1Txt |
    .//Filer/USAddress/AddressLine2Txt |
    .//Filer/USAddress/CityNm |
    .//Filer/USAddress/StateAbbreviationCd |
    .//Filer/USAddress/ZIPCd
""", namespaces=NAMESPACES)

# Organization type union XPath (moved from parse_990.py)
ORG_TYPE_UNION_XPATH = etree.XPath("""
    .//irs:IRS990/irs:Organization501cInd |
    .//irs:IRS990/irs:Organization501c3Ind |
    .//irs:IRS990/irs:Organization4947a1NotPFInd |
    .//irs:IRS990/irs:Organization4947a1TrtdPFInd |
    .//IRS990/Organization501cInd |
    .//IRS990/Organization501c3Ind |
    .//IRS990/Organization4947a1NotPFInd |
    .//IRS990/Organization4947a1TrtdPFInd
""", namespaces=NAMESPACES)

# Header union XPath combining form_type, tax_year, and filer_ein XPaths
HEADER_UNION_XPATH = etree.XPath("""
    .//irs:ReturnHeader/irs:ReturnTypeCd |
    .//ReturnHeader/ReturnTypeCd |
    .//irs:ReturnHeader/irs:TaxYr |
    .//ReturnHeader/TaxYr |
    .//irs:Filer/irs:EIN |
    .//Filer/EIN
""", namespaces=NAMESPACES)


