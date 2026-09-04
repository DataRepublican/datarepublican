Charity changes for percentages:
	* we need to collect all the income for a charity. this is quickly available in the <CYTotalRevenueAmt> XML tag. This should be stored in the denominator column.
	* we will need a clamp function on 
	* Once we collect this field we can calculate the percent fields in prep_for_insert
		* we will need to clamp values > 100 at 101, and below 0 at -1 we'll call that function clamp() below.
	 in the charity class as follows:
		comp_pct = clamp(officer_comp/(denominator or 1) * 100)
		travel_pct = clamp(travel_amt/(denominator or 1) * 100)
		conferences_pct = clamp(conferences_amt/(denominator or 1) * 100)
		grants_pct = clamp(grants_to_others/(denominator or 1) * 100)
		foreign_expenses_pct = clamp((foreign_expenses)/(denominator or 1) * 100)

