"""
charity_types.py - Dictionary of IRS 501(c) and 4947(a)(1) organization types.

This module defines a constant dictionary ORGANIZATION_TYPES with details for each
501(c)(1) through 501(c)(29) and 4947(a)(1) organization type, including short
description, purpose, key restrictions, and donations deductibility. Data is sourced
from IRS Publication 557 and web references, adapted from
501c_organization_types.md for use in scripts processing nonprofit data.

Example usage:
    from charity_types import ORGANIZATION_TYPES
    org_info = ORGANIZATION_TYPES["501(c)(3)"]
    print(org_info["short_description"])  # Output: Charities
"""

ORGANIZATION_TYPES = {
    "501(c)(1)": {
        "short_description": "Federal Entities",
        "purpose": "Corporations organized under an Act of Congress (e.g., Federal Credit Unions, Federal Reserve Banks). Serve public purposes like banking or housing.",
        "key_restrictions": "No Form 1024, 990 filing exempt. Contributions deductible only for public purposes. No Grift.",
        "donations_deductible": "Yes (public purposes)"
    },
    "501(c)(2)": {
        "short_description": "Property Holding",
        "purpose": "Title-holding corporations for exempt organizations. Hold property and provide income (less expenses) to a tax-exempt parent organization.",
        "key_restrictions": "Income must be paid to exempt parent. Limited to property management. No Grift. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(3)": {
        "short_description": "Charities",
        "purpose": "Charitable, religious, educational, scientific, literary organizations, or those testing for public safety, fostering amateur sports, or preventing cruelty to children/animals. Includes public charities (e.g., CHAI) and private foundations.",
        "key_restrictions": "No Grift. No substantial lobbying (501(h) election allows limited lobbying). No political campaign activity. File Form 1023 once, 990 annually.",
        "donations_deductible": "Yes"
    },
    "501(c)(4)": {
        "short_description": "Civic Welfare",
        "purpose": "Civic leagues or social welfare organizations promoting community welfare (e.g., homeowners associations, volunteer fire companies).",
        "key_restrictions": "No Grift. Unlimited lobbying if related to purpose. Contributions not tax-deductible unless for specific purposes (e.g., fire departments). File Form 1024 once, 990 annually.",
        "donations_deductible": "No (except specific cases)"
    },
    "501(c)(5)": {
        "short_description": "Labor/Agriculture",
        "purpose": "Labor, agricultural, or horticultural organizations (e.g., unions, farm bureaus). Promote worker rights or agricultural interests.",
        "key_restrictions": "No Grift. Lobbying allowed if related to purpose. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(6)": {
        "short_description": "Business Leagues",
        "purpose": "Business leagues, chambers of commerce, or professional associations (e.g., American Solar Grazing Association). Improve business conditions.",
        "key_restrictions": "No Grift. Unlimited lobbying for business interests. Contributions deductible as business expenses. File Form 1024 once, 990 annually.",
        "donations_deductible": "No (business expense)"
    },
    "501(c)(7)": {
        "short_description": "Social Clubs",
        "purpose": "Social or recreational clubs (e.g., country clubs, fraternities). Provide leisure activities for members.",
        "key_restrictions": "Non-discriminatory policy (except religion). Minimal public use (<$2,500/year or <5% receipts). Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(8)": {
        "short_description": "Fraternal Benefits",
        "purpose": "Fraternal beneficiary societies operating under a lodge system, providing life, sickness, or other benefits (e.g., Elks).",
        "key_restrictions": "Must offer insurance/benefits. Non-discriminatory except for religion. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(9)": {
        "short_description": "Employee Benefits",
        "purpose": "Voluntary employees’ beneficiary associations providing life, sickness, or accident benefits to members (e.g., labor union benefits).",
        "key_restrictions": "Membership voluntary, tied to employer/union. No discrimination in benefits. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(10)": {
        "short_description": "Fraternal Charity",
        "purpose": "Domestic fraternal societies without insurance, devoting earnings to charitable, religious, or educational purposes (e.g., Masons).",
        "key_restrictions": "No insurance benefits. Funds for exempt purposes. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(11)": {
        "short_description": "Teacher Pensions",
        "purpose": "Teachers’ retirement fund associations. Pay retirement benefits to local teachers/school employees.",
        "key_restrictions": "Funded by taxes, donations, investments. Local scope. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(12)": {
        "short_description": "Mutual Utilities",
        "purpose": "Local benevolent life insurance associations, mutual irrigation, or telephone companies. Serve members’ needs.",
        "key_restrictions": "85%+ income from members for losses/expenses. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(13)": {
        "short_description": "Cemeteries",
        "purpose": "Cemetery companies operated for members or charitable purposes.",
        "key_restrictions": "No private profit. Funds for maintenance. Contributions deductible if charitable. File Form 1024 once, 990 annually.",
        "donations_deductible": "Yes (if charitable)"
    },
    "501(c)(14)": {
        "short_description": "Credit Unions",
        "purpose": "State-chartered credit unions or mutual reserve funds. Provide financial services to members.",
        "key_restrictions": "State-regulated. No Grift. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(15)": {
        "short_description": "Small Insurance",
        "purpose": "Mutual insurance companies or associations (small insurers). Provide insurance to members.",
        "key_restrictions": "Gross receipts <$500,000. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(16)": {
        "short_description": "Crop Finance",
        "purpose": "Cooperative organizations financing crop operations. Support agricultural activities.",
        "key_restrictions": "Funds for crop financing. No private profit. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(17)": {
        "short_description": "Unemployment Funds",
        "purpose": "Supplemental unemployment benefit trusts. Pay benefits to employees during layoffs.",
        "key_restrictions": "Benefits only for involuntary layoffs. No Grift. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(18)": {
        "short_description": "Old Pensions",
        "purpose": "Employee-funded pension trusts (pre-1959). Provide pension benefits.",
        "key_restrictions": "Employee-funded only. No diversion of funds. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(19)": {
        "short_description": "Veterans Groups",
        "purpose": "Veterans’ organizations providing benefits or social activities for members.",
        "key_restrictions": "75%+ members are veterans. Contributions deductible if 90%+ for exempt purposes. File Form 1024 once, 990 annually.",
        "donations_deductible": "Yes (90%+ exempt)"
    },
    "501(c)(20)": {
        "short_description": "Legal Services",
        "purpose": "Group legal services organizations (discontinued after 1992). Provided legal benefits.",
        "key_restrictions": "Obsolete. No new exemptions.",
        "donations_deductible": "No"
    },
    "501(c)(21)": {
        "short_description": "Black Lung Trusts",
        "purpose": "Black lung benefit trusts. Fund benefits for coal miners.",
        "key_restrictions": "Specific to black lung claims. Contributions deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "Yes"
    },
    "501(c)(22)": {
        "short_description": "Pension Liability",
        "purpose": "Withdrawal liability payment funds. Manage employer pension liabilities.",
        "key_restrictions": "Specific to pension plans. No Grift. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(23)": {
        "short_description": "Old Veterans",
        "purpose": "Veterans’ organizations (pre-1880, benefits-focused). Similar to 501(c)(19) but older.",
        "key_restrictions": "Rare. Contributions deductible if for exempt purposes. File Form 1024 once, 990 annually.",
        "donations_deductible": "Yes (exempt purposes)"
    },
    "501(c)(24)": {
        "short_description": "ERISA Trusts",
        "purpose": "Trusts for ERISA Section 4049 plans (post-1980 groundwork for organizations with significant grants or foreign expenses).",
        "key_restrictions": "Specific to ERISA plans. No Grift. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(25)": {
        "short_description": "Multi-Parent Hold",
        "purpose": "Title-holding corporations with multiple parents. Hold property for exempt orgs.",
        "key_restrictions": "Up to 35 parents. Income to exempt orgs. No Grift. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(26)": {
        "short_description": "High-Risk Health",
        "purpose": "State-sponsored high-risk health insurance organizations. Provide coverage to high-risk individuals.",
        "key_restrictions": "State-regulated. No private profit. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(27)": {
        "short_description": "Workers Comp",
        "purpose": "State-sponsored workers’ compensation reinsurance organizations. Manage insurance risks.",
        "key_restrictions": "State-regulated. No Grift. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(28)": {
        "short_description": "Railroad Pensions",
        "purpose": "National Railroad Retirement Investment Trust. Manage railroad retirement funds.",
        "key_restrictions": "Specific to railroad pensions. No Grift. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "501(c)(29)": {
        "short_description": "CO-OP Health",
        "purpose": "CO-OP health insurance issuers under ACA. Provide consumer-oriented health plans.",
        "key_restrictions": "ACA-specific. No private profit. Contributions not deductible. File Form 1024 once, 990 annually.",
        "donations_deductible": "No"
    },
    "4947(a)(1)": {
        "short_description": "Charitable Trusts",
        "purpose": "Nonexempt charitable trusts treated as private foundations for charitable purposes.",
        "key_restrictions": "No Grift. Subject to private foundation rules (e.g., excise taxes, distributions). File Form 1023 once, 990 annually.",
        "donations_deductible": "Yes"
    }
}