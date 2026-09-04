# Geocoding API cleanup 

Attached you will find the following files: address.py, geocoding.py, geocoding_api_processor.py, pipeline.py

## Context
This is all code in the context of processing addresses from IRS 990 filings by NGOs. Not surprisingly the data is crap. What we're trying to do is geolocate the addresses, we then round the lat/long to the nearest 0.0001 degrees, which is about 11m at the equator, the justification for that is that corresponds to a single building. Premise is that multiple NGOs in the same building are really all one giant NGO. This is stored as something called a "colocator" which is stored as LL:lat:long
* PO boxes are handled by using a special code PO:zip:box since geolocate doesn't make sense for them. 
* Addresses arrive pre-parsed with the following fields: line1, line2*, city, state, zip, zip4; with the * fields being optional. 
* We construct a "canonical" address string from those fields, we in a separate process produce the geocoding records for each unique address. But that canonical string, though tempting to use because of the name, is inferior to the parsed form because many APIs would prefer the parsed out fields. Those are stored in the geocoding record as a JSON encoded dictionary as "normalized_address". 
* Most of the other code doesn't need API calls, it's purely local interactions, it reads from a local file or duckdb table and writes back to a duckdb table. In this case, we had to build a SEDA pipeline to deal with the challenges. 

## The problem
* So we did a huge refactor, and we lost some code in the process, so the census processing code was breaking. In the process of reviewing it, we discovered we were using an old csv based version of the Census library, so we've switched to the new library, censusbatchgeocoder instead. 
* But that code was also using the canonical string and trying to parse it, which is a no-no. 

## The Tasks
* Right now, we're passing around WorkUnits with bare dictionaries. I general, I would prefer if we used real class objects, because I think it makes the code cleaner. This is especially true for this use case, because it would be nice if there was an accessor for the normalized_address that parsed the JSON and then cached it inside the instance object. So the first task is to create a sub-class of the WorkUnit for use by the pipeline in all the handlers that carries the fields fetched by the feed thread. 
* Since the Census API turned out to be using the non-parsed data, I want to review all the API implementations to make sure they're using the structured data, not the non-structured data. 

## Deliverables
* The Python code for the new GeocodingWorkUnit class, which I will add at the top of geocoding_api_processor.py
* The update handler methods that use the structured form, but one at a time, with discussion first. 

#GrumpyNews #GrokNews News with the 🐂💩 removed via a grok prompt, which I share. Be informed, not manipulated. IT = Directionally True (Irish), LT = Lizard True (Lawyer), 5 🌐5 🇺🇸