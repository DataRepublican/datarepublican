# Backfill steps

## Background
So some non-profits don't have to file a 990: Religious orgs, local governments (including state universities, etc.). But they're definitely part of the ecosystem. In the old TSV version there was a lot of code that tried to reverse engineer the existence of these non-profits by finding grants and taking the name and EINs from the grant declaration, and "backfilling" the creation of placeholder charities. 

## Tasks
* This should be done as part of the "match" step since you're going to be matching grants by address anyways.  
* Look for EINs and grant addresses that don't match an existing Charity record. This will be a huge ugly join. 
* For each one found, match the grant by colocator to create a new Backfill record with the information known from the grant: the EIN if available, the address, colocator, and the name. If multiple matches are found, take the one with the largest denominator. Since we're matching by colocator, no need to geolocate the address, just copy that information over from the existing address record. 
