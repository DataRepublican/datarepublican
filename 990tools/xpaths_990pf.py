#!/usr/bin/env python3
"""
xpaths_990pf.py - XPath configurations specific to Form 990PF

This module contains XPath expressions specific to IRS Form 990PF.
Universal XPaths are imported from xpaths.py.
"""

from lxml import etree
try:
    from xpaths import COMMON_XPATHS, NAMESPACES
except ImportError:
    from xpaths import COMMON_XPATHS, NAMESPACES

# Form 990PF specific XPath configurations
XPATHS_990PF = {
    **COMMON_XPATHS,  # Include all common patterns
    "receipt": [
        etree.XPath(".//irs:IRS990PF/irs:AnalysisOfRevenueAndExpenses/irs:TotalRevAndExpnssAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:AnalysisOfRevenueAndExpenses/irs:TotalRevAndExpnssAmt", namespaces=NAMESPACES),
    ],
    "total_exp": [
        etree.XPath(".//irs:IRS990PF/irs:AnalysisOfRevenueAndExpenses/irs:TotalExpensesRevAndExpnssAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:AnalysisOfRevenueAndExpenses/irs:TotalExpensesRevAndExpnssAmt", namespaces=NAMESPACES),
    ],
    "prog_exp": [
        etree.XPath(".//irs:IRS990PF/irs:AnalysisOfRevenueAndExpenses/irs:ContriPaidDsbrsChrtblAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:AnalysisOfRevenueAndExpenses/irs:ContriPaidDsbrsChrtblAmt", namespaces=NAMESPACES),
    ],
    "schedule_expenses": [
        etree.XPath(".//irs:OtherExpensesSchedule/irs:OtherExpensesScheduleGrp", namespaces=NAMESPACES),
    ],
    "expense_value": [
        etree.XPath("irs:RevenueAndExpensesPerBooksAmt", namespaces=NAMESPACES),
        etree.XPath("irs:NetInvestmentIncomeAmt", namespaces=NAMESPACES),
        etree.XPath("irs:DisbursementsCharitablePrpsAmt", namespaces=NAMESPACES),
    ],
    "expense_desc": [
        etree.XPath("irs:Desc", namespaces=NAMESPACES),
    ],
    "officer_comp_elements": [
        etree.XPath(".//irs:IRS990PF/irs:OfficerDirTrstKeyEmplInfoGrp/irs:OfficerDirTrstKeyEmplGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:OfficerDirTrstKeyEmplInfoGrp/irs:OfficerDirTrstKeyEmplGrp", namespaces=NAMESPACES),
    ],
    "officer_comp": [
        etree.XPath(".//irs:IRS990PF/irs:OfficerDirTrstKeyEmplInfoGrp/irs:OfficerDirTrstKeyEmplGrp/irs:CompensationAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:OfficerDirTrstKeyEmplInfoGrp/irs:OfficerDirTrstKeyEmplGrp/irs:CompensationAmt", namespaces=NAMESPACES),
    ],
    "grants_to_others": [
        etree.XPath(".//irs:IRS990PF/irs:SupplementaryInformationGrp/irs:TotalGrantOrContriPdDurYrAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:SupplementaryInformationGrp/irs:TotalGrantOrContriPdDurYrAmt", namespaces=NAMESPACES),
    ],
    "org_type": [
        etree.XPath(".//irs:IRS990PF/irs:Organization501c3ExemptPFInd", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990PF/irs:Organization4947a1TrtdPFInd", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990PF/irs:Organization501c3TaxablePFInd", namespaces=NAMESPACES),
        etree.XPath(".//irs:Organization501c3ExemptPFInd", namespaces=NAMESPACES),
        etree.XPath(".//irs:Organization501c3TaxablePFInd", namespaces=NAMESPACES),
    ],
    "total_assets": [
        etree.XPath(".//irs:IRS990PF/irs:Form990PFBalanceSheetsGrp/irs:TotalAssetsEOYAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:Form990PFBalanceSheetsGrp/irs:TotalAssetsEOYAmt", namespaces=NAMESPACES),
    ],
    "total_assets_boy": [
        etree.XPath(".//irs:IRS990PF/irs:Form990PFBalanceSheetsGrp/irs:TotalAssetsBOYAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:Form990PFBalanceSheetsGrp/irs:TotalAssetsBOYAmt", namespaces=NAMESPACES),
    ],
    "total_liabilities": [
        etree.XPath(".//irs:IRS990PF/irs:Form990PFBalanceSheetsGrp/irs:TotalLiabilitiesEOYAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:Form990PFBalanceSheetsGrp/irs:TotalLiabilitiesEOYAmt", namespaces=NAMESPACES),
    ],
    "net_assets": [
        etree.XPath(".//irs:IRS990PF/irs:Form990PFBalanceSheetsGrp/irs:TotNetAstOrFundBalancesEOYAmt", namespaces=NAMESPACES),
        etree.XPath(".//irs:Form990PFBalanceSheetsGrp/irs:TotNetAstOrFundBalancesEOYAmt", namespaces=NAMESPACES),
    ],
    "contractor_elements": [
        etree.XPath(".//irs:ReturnData/irs:IRS990PF/irs:CompensationOfHghstPdCntrctGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:IRS990PF/irs:CompensationOfHghstPdCntrctGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:CompensationOfHghstPdCntrctGrp", namespaces=NAMESPACES),
    ],
    "contractor_name_line1": [
        etree.XPath("irs:BusinessName/irs:BusinessNameLine1Txt", namespaces=NAMESPACES),
        etree.XPath("irs:BusinessName/irs:BusinessNameLine1", namespaces=NAMESPACES),
        etree.XPath("BusinessName/BusinessNameLine1Txt"),
        etree.XPath("BusinessName/BusinessNameLine1"),
    ],
    "contractor_name_line2": [
        etree.XPath("irs:BusinessName/irs:BusinessNameLine2Txt", namespaces=NAMESPACES),
        etree.XPath("irs:BusinessName/irs:BusinessNameLine2", namespaces=NAMESPACES),
        etree.XPath("BusinessName/BusinessNameLine2Txt"),
        etree.XPath("BusinessName/BusinessNameLine2"),
    ],
    "contractor_address_line1": [
        etree.XPath("irs:USAddress/irs:AddressLine1Txt", namespaces=NAMESPACES),
        etree.XPath("irs:USAddress/irs:AddressLine1", namespaces=NAMESPACES),
        etree.XPath("USAddress/AddressLine1Txt"),
        etree.XPath("USAddress/AddressLine1"),
    ],
    "contractor_address_line2": [
        etree.XPath("irs:USAddress/irs:AddressLine2Txt", namespaces=NAMESPACES),
        etree.XPath("irs:USAddress/irs:AddressLine2", namespaces=NAMESPACES),
        etree.XPath("USAddress/AddressLine2Txt"),
        etree.XPath("USAddress/AddressLine2"),
    ],
    "contractor_city": [
        etree.XPath("irs:USAddress/irs:CityNm", namespaces=NAMESPACES),
        etree.XPath("USAddress/CityNm"),
    ],
    "contractor_state": [
        etree.XPath("irs:USAddress/irs:StateAbbreviationCd", namespaces=NAMESPACES),
        etree.XPath("USAddress/StateAbbreviationCd"),
    ],
    "contractor_zip_code": [
        etree.XPath("irs:USAddress/irs:ZIPCd", namespaces=NAMESPACES),
        etree.XPath("USAddress/ZIPCd"),
    ],
    "grant_elements": [
        etree.XPath(".//irs:IRS990PF/irs:SupplementaryInformationGrp/irs:GrantOrContributionPdDurYrGrp", namespaces=NAMESPACES),
        etree.XPath(".//irs:SupplementaryInformationGrp/irs:GrantOrContributionPdDurYrGrp", namespaces=NAMESPACES),
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
        etree.XPath("irs:TotalGrantOrContriPdDurYrAmt", namespaces=NAMESPACES),
        etree.XPath("irs:GrantOrContributionAmt", namespaces=NAMESPACES),
        etree.XPath("irs:Amount", namespaces=NAMESPACES),
    ],
}