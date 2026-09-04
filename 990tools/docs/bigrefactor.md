Ok, grok, buckle up, we're going to do a giant refactor of the code. 

# What it does

What this code does is process IRS form 990 files, which are filed by non-profit corporations to declare where the money goes.
Unfortunately, the love of money is the root of all evil, and unwatched people tend towards corruption. 
So I've built a visualization using d3 to build a sankey diagram that shows the flows between different areas. 
It's working so far, but its time for the code to evolve.

# Where

* You're looking at the top level directory, but all the _code_ is in 990tools.
* All the data is in /Volumes/Data as follows:
	* ZIPS_DIR="/Volumes/Data/irs_zips"
	* OUT_DIR="/Volumes/Data/tsvs"
	* ANAL_DIR="/Volumes/Data/atsvs"
	* FINAL_DIR="/Volumes/Data/final"
	
* the code is laid out as follows
	* DR_ROOT="$HOME/Development/datarepublican" what you're looking at now.
	* TOOLS=$DR_ROOT/990tools The directory where the code lives.
	* BROWSE=$DR_ROOT/browse The directory where the code for the diagram lives, which is not related to the task today. 
* To be very clear: ./990tools is for code, /Volumes/Data is for data. The one exception to this is the ./990tools/test_xmls folder, which I'll get to in a moment. 
	
# Task
## The old, now broken stuff. 
This code worked by extracting the data from the XML files into tsv files, then reloading the .tsv files, then reparsing the xml files. 
It also worked by being a collection of scripts for each step. 
## New goals
Fundamentally, we want to ditch the writing tsv files, then reloading them. Instead, we want to:
1. Create dataclass objects for each type of data: Those types are: Charity, Grant, Contract, Contractor, Political Contribution, Address, ZipFile, XMLFile. Passing raw rows around is very cumbersome, and not very DRY. 
2. Store them in an sqlite database. 
3. Process them there, and repeat as necessary. 
4. Geolocation:
	Background: originally we were doing 2 things that turned out to be a problem. 
		* While grants have to be reported by EIN for the 990ez and 990 forms, for the 990pf forms only the address is used.
		* Not all charities file a 990 form, most commonly, state universities are considered part of local government so they don't have to. 
	Old solution: So the way this was resolved was by recording name/zip for grants/donations and using a simple name hueristic to match back to known 990 orgs, and to infer the existence of those orgs.
	Miss: It's harder to find corruption that way, because there's a lot of self dealing between 501c3/501c4, different name, same address. Also, we want to eventually start matching against 527 data (Political Action Committees). Also, the addresses are generally provided pre-parsed, taking them to strings and back was a bad pattern. 
	New solution: Turns out, that there's a better way to do this, which is that the census department has an API that can take 10,000 addresses at a time, and return their lat/long with a python module called censusgeocode. There's a bit of a chicken/egg problem there, because the addresses have to be collected first, geolocated, and then matched. That doesn't work for foreign addresses, but we don't care, we can just map them by country code. 
5. Only as a final step do we need to extract a subset of columns from the database, export those to .tsv files, and make sure that all other files we're loading that provide edges match to an existing charity. 

# Things you need to know:
* The filenames in the XML files have no relation to tax year or EIN. Also, the year on the .zip files always lags, so the 2019 files tend to have 2018 tax years, etc. The scripts take tax years as an input but the tax year for processing zip files does not apply for processing other files. 
* There is a directory called ./990tools/test_xmls that contain pre-extracted XML files, that you can examine for clues tests. One of them is 230M though, so don't blindly read them, pull them selectively. 
* The code you're looking at now works, so if it breaks, that's on you. 
* We have to run this code once/month and one of the reason it was broken into multiple independent scripts was that if a step broke it could be hand tweaked and patched around. 
* While past versions of this code used to filter the Charities to only large ones, that turned out to be a bad plan, so I use to manually use the complete file.
* The scale: There are 2.8M XML files, which slim down to 910,000 charities. So the existing code uses a lot of worker threads to process thing efficiently. 

# Suggested processing steps

1. read the prompt here for tips about structuring code well: https://raw.githubusercontent.com/twinforces/grok-prompts/refs/heads/better-code/better_code.j2
2. Read the directory with the zip files as specified in the args. 
3. Pull the list of zip files available from the IRS site, see if there are any new ones to be downloaded for processing, if so, do so and register it.
4. Use command line tools to get a listing of each zip file, and register the zip as ZipFile in the database, and the contents as XMLFile
5. For each XML file, process it to extra the data to fill out objects, which is then stored in the database, annotate the XMLFile with the EIN and tax year. 
6. Store addresses in the database as well, keeping them parsed into pieces since they're provided to you that way by the XML, for foreign addresses store just the country code, only insert an address once. 
6a. Make an address entry in the database and matching charity for all country codes, as defined in countryCodes.py.
7. With 4 threads in batches of 5000 addresses at a time, geo-locate the non PO Box or foreign addresses. Make something called a "colocator" column on the Charity/Contractor table that will let us catch people double dealing, store their lat/long as LL:lat:long, and use PO:box:Zipcode for the PO Boxes, FA:<country code> for foreign addresses.  
8. Extract and store the grant, officer, political contribution and contractor data from the XML files, with associated address info while preventing duplicates. 
9. Match grants with no EIN, match by address using the lat long data, and generate stub charity records for those Charities if not found. 
10. Do percentile analysis on all the charities in a group by org type and tax year. 
11. Output TSV files for the charities, grants, contracts, contractors, and political contributions. 

# Further suggestions
* This is a big task, perhaps it makes the most sense to do it one stage at a time with tests from the test_xmls. 
* having a whole pile of interrelated scripts that are leveraging each other makes no sense, this should probably be one giant python module called 990processor or something. 
