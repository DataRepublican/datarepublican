#!/usr/bin/env python3
"""
xpaths_990ez.py - XPath configurations specific to Form 990EZ

This module contains XPath expressions specific to IRS Form 990EZ.
Universal XPaths are imported from xpaths.py.
"""

from lxml import etree
try:
    from xpaths import COMMON_XPATHS, NAMESPACES
except ImportError:
    from xpaths import COMMON_XPATHS, NAMESPACES

# Form 990EZ specific XPath configurations
XPATHS_990EZ = {
    **COMMON_XPATHS,  # Include all common patterns
    "receipt": [
        etree.XPath(".//irs:IRS990EZ/irs:GrossReceiptsAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990EZ/irs:TotalRevenueAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:GrossReceiptsAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:TotalRevenueAmt", namespaces=NAMESPACES),
    ],
    "contributions": [
        etree.XPath(".//irs:TotalContributionsAmt", namespaces=NAMESPACES),
    ],
    "total_exp": [
        etree.XPath(".//irs:IRS990EZ/irs:TotalExpensesAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:TotalExpensesAmt", namespaces=NAMESPACES),
    ],
    "prog_exp": [
        etree.XPath(".//irs:IRS990EZ/irs:TotalProgramServiceExpensesAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:TotalProgramServiceExpensesAmt", namespaces=NAMESPACES),
    ],
    "schedule_o": [
        etree.XPath(".//irs:IRS990ScheduleO/irs:SupplementalInformationDetail", namespaces=NAMESPACES),
    ],
    "officer_comp_elements": [
        etree.XPath(".//irs:IRS990EZ/irs:OfficerDirectorTrusteeEmplGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:OfficerDirectorTrusteeEmplGrp", namespaces=NAMESPACES),
    ],
    "officer_comp": [
        etree.XPath(".//irs:IRS990EZ/irs:OfficerDirectorTrusteeEmplGrp/irs:CompensationAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:OfficerDirectorTrusteeEmplGrp/irs:CompensationAmt", namespaces=NAMESPACES),
    ],
    "grants_to_others": [
        etree.XPath(".//irs:ReturnData/irs:IRS990EZ/irs:IRS990ScheduleF/irs:GrantsToOrgOutsideUSGrp/irs:CashGrantAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:ReturnData/irs:IRS990EZ/irs:IRS990ScheduleF/irs:GrantsToOrganizationsOutsideUS/irs:CashGrantAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:ReturnData/irs:IRS990EZ/irs:IRS990ScheduleF/irs:GrantsToOrgsOutsideUS/irs:CashGrantAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:ReturnData/irs:IRS990EZ/irs:IRS990ScheduleF/irs:ForeignIndividualsGrantsGrp/irs:CashGrantAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:ReturnData/irs:IRS990EZ/irs:IRS990ScheduleI/irs:RecipientTable/irs:CashGrantAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:ReturnData/irs:IRS990EZ/irs:IRS990ScheduleI/irs:GrantsOtherAsstToIndivInUSGrp/irs:CashGrantAmt", namespaces=NAMESPACES),
    ],
    "grant_elements_f": [
        etree.XPath(".//irs:ReturnData/irs:IRS990EZ/irs:IRS990ScheduleF", namespaces=NAMESPACES),
    ],
    "grant_sub_elements_f": [
        etree.XPath(".//irs:GrantsToOrgOutsideUSGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:GrantsToOrganizationsOutsideUS", namespaces=NAMESPACES),
        etree.XPath(".//irs:GrantsToOrgsOutsideUS", namespaces=NAMESPACES),
        etree.XPath(".//irs:ForeignIndividualsGrantsGrp", namespaces=NAMESPACES),
    ],
    "grant_elements_i": [
        etree.XPath(".//irs:ReturnData/irs:IRS990EZ/irs:IRS990ScheduleI", namespaces=NAMESPACES),
    ],
    "grant_sub_elements_i": [
        etree.XPath(".//irs:RecipientTable", namespaces=NAMESPACES),
        etree.XPath(".//irs:GrantsOtherAsstToIndivInUSGrp", namespaces=NAMESPACES),
    ],
    "grant_elements_o": [
        etree.XPath(".//irs:IRS990ScheduleO/irs:SupplementalInformationDetail", namespaces=NAMESPACES),
    ],
    "foreign_expenses": [
        etree.XPath(".//irs:ReturnData/irs:IRS990EZ/irs:IRS990ScheduleF/irs:StmtOfActyOutsdUSGrp/irs:RegionTotalExpendituresAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:ReturnData/irs:IRS990EZ/irs:IRS990ScheduleF/irs:AccountActivitiesOutsideUSGrp/irs:RegionTotalExpendituresAmt", namespaces=NAMESPACES),
    ],
    "foreign_exp_elements": [
        etree.XPath(".//irs:ReturnData/irs:IRS990EZ/irs:IRS990ScheduleF", namespaces=NAMESPACES),
    ],
    "foreign_exp_sub_elements": [
        etree.XPath(".//irs:StmtOfActyOutsdUSGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:AccountActivitiesOutsideUSGrp", namespaces=NAMESPACES),
    ],
    "org_type": [
        etree.XPath(".//irs:IRS990EZ/irs:Organization501c3Ind", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990EZ/irs:Organization501cInd", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990EZ/irs:Organization4947a1NotPFInd", namespaces=NAMESPACES),
    ],
    "foreign_office": [
        etree.XPath(".//irs:IRS990EZ/irs:ForeignOfficeInd", namespaces=NAMESPACES),
        etree.XPath(".//irs:ForeignOfficeCountryCd", namespaces=NAMESPACES),
    ],
    "total_assets": [
        etree.XPath(".//irs:IRS990EZ/irs:TotalAssetsEOYAmt", namespaces=NAMESPACES),
    ],
    "contractor_elements": [
        etree.XPath(".//irs:ReturnData/irs:IRS990EZ/irs:ContractorCompensationGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990EZ/irs:ContractorCompensationGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:ContractorCompensationGrp", namespaces=NAMESPACES),
    ],
    "contractor_name_line1": [
        etree.XPath("irs:ContractorName/irs:BusinessName/irs:BusinessNameLine1Txt", namespaces=NAMESPACES),
        etree.XPath("irs:ContractorName/irs:BusinessNameLine1Txt", namespaces=NAMESPACES),
        etree.XPath("ContractorName/BusinessName/BusinessNameLine1Txt"),
        etree.XPath("ContractorName/BusinessNameLine1Txt"),
    ],
    "contractor_name_line2": [
        etree.XPath("irs:ContractorName/irs:BusinessName/irs:BusinessNameLine2Txt", namespaces=NAMESPACES),
        etree.XPath("irs:ContractorName/irs:BusinessNameLine2Txt", namespaces=NAMESPACES),
        etree.XPath("ContractorName/BusinessName/BusinessNameLine2Txt"),
        etree.XPath("ContractorName/BusinessNameLine2Txt"),
    ],
    "contractor_address_line1": [
        etree.XPath("irs:ContractorAddress/irs:USAddress/irs:AddressLine1Txt", namespaces=NAMESPACES),
        etree.XPath("irs:ContractorAddress/irs:USAddress/irs:AddressLine1", namespaces=NAMESPACES),
        etree.XPath("ContractorAddress/USAddress/AddressLine1Txt"),
        etree.XPath("ContractorAddress/USAddress/AddressLine1"),
    ],
    "contractor_address_line2": [
        etree.XPath("irs:ContractorAddress/irs:USAddress/irs:AddressLine2Txt", namespaces=NAMESPACES),
        etree.XPath("irs:ContractorAddress/irs:USAddress/irs:AddressLine2", namespaces=NAMESPACES),
        etree.XPath("ContractorAddress/USAddress/AddressLine2Txt"),
        etree.XPath("ContractorAddress/USAddress/AddressLine2"),
    ],
    "contractor_city": [
        etree.XPath("irs:ContractorAddress/irs:USAddress/irs:CityNm", namespaces=NAMESPACES),
        etree.XPath("ContractorAddress/USAddress/CityNm"),
    ],
    "contractor_state": [
        etree.XPath("irs:ContractorAddress/irs:USAddress/irs:StateAbbreviationCd", namespaces=NAMESPACES),
        etree.XPath("ContractorAddress/USAddress/StateAbbreviationCd"),
    ],
    "contractor_zip_code": [
        etree.XPath("irs:ContractorAddress/irs:USAddress/irs:ZIPCd", namespaces=NAMESPACES),
        etree.XPath("ContractorAddress/USAddress/ZIPCd"),
    ],
    "grant_ein_xpaths": [
        etree.XPath("irs:RecipientEIN", namespaces=NAMESPACES),
        etree.XPath("irs:EIN", namespaces=NAMESPACES),
    ],
    "grant_name_xpaths": [
        etree.XPath("irs:RecipientNameBusiness", namespaces=NAMESPACES),
        etree.XPath("irs:RecipientBusinessName/irs:BusinessNameLine1Txt", namespaces=NAMESPACES),
        etree.XPath("irs:BusinessName/irs:BusinessNameLine1Txt", namespaces=NAMESPACES),
    ],
    "grant_amount_xpaths": [
        etree.XPath("irs:CashGrantAmt", namespaces=NAMESPACES),
    ],
}