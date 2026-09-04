# 990Tools Architecture
This document describes the architecture of this 990tools folder, our Python scripts for parsing IRS 990, 990EZ, and 990PF forms.

## Development Rules
* read https://gist.github.com/twinforces/ab9b8f303504de932b0b85558b4c0a22 for general instructions on writing better code.
* read https://gist.github.com/twinforces/37fed6f279cd8a2d118c405ff6a26911 for instructions on how to do your work. 
* read ./990tools/docs/grok.md to get a grok summary of this document.
* read ./990tools/docs/grok_todo.md to get a broad over view of the goals

## Layouts and minutia
* all python code is in ./990tools, no need to look for it else where.
* The live database is in duckdb and lives in /Volumes/Data/final/irs990.db
* IRS zip files live in /Volumes/Data/irs_zips
* other paths are defined in constants.py but are mostly irrelevant at this point. 
* Remember that the live database has data, but any test database you generate will be empty. Running a test and then not finding data and concluding there is no work to do makes you stupid. 
* there are some test XML files in ./990tools/test_xmls/ The ones beginning with FAIL are intentionally broken.
* Don't use fake addresses. If you must extract some addresses from the test_xmls. Grep for 'USAddress>' with -B 10. 
* This document lives in ./990tools/docs/Architecture.md and can be added to as necessary as your understanding improves.
* grok.md is your understanding of the Architecture at this point. 
* grok_todo.md is your understanding of the things left to be done from auditing the code and its about 90% correct. 

## Purpose
* The purpose of this code is to parse IRS XML tax return files and store them in a duckdb database for later analysis. This is broken out into the following stages:
	* irsfetch - this checks against the IRS website, then downloads any zips that aren't present
	* zip - this goes through the zips creating ZipFile, and XmlFile records
	* xml - this goes through the 2.9M XmlFile records and parses them and creates Charity, Grant, Contribution, Political Contribution, and Address records
	* address - this goes through the resulting 4M addresses and de-duplicates them by designating the first address found to be the "master" address in preparation for the next step.
	* geolocate - this takes up to 10000 addresses at a time and uses the census geolocate service to find the lat/long for any non PO-BOX or foreign address
	* there are other steps but they haven't been debugged yet, so we can ignore them.
	
* Immutable architecture facts
	* duckdb will not allow multiple writers to the database, but multiple readers are ok
	* My lap top has 16 cores, and this is mostly I/O bound. There is a meta-script set_ worker_threads.py that can be used to use binary search to determine the magic number of worker threads for each step. So we should use a ThreadPoolExecutor for the N read threads, and then a single consumer thread that does all the writing
	* That said, logic can drive the threading for each stage:
		* irsfetch - The only thing where multiple threads make sense is for the download of multiple zip files, in parallel which doesn't happen that often. This also doesn't write to the database.
		* zip - this is I/O bound in that it needs to read from a single zip file at a time then generate up to a half million XmlFile records, at most 2 threads make sense
		* xml - this is the true multithreaded beast. Decompressing the data from the zip file dominates, then it needs to be parsed, and records need to be written to the database by the consumer threads
		* address - this is pure duckdb, it sets up the master addresses and creates geocoding objects to set the colocator fields in the objects that own the master and child addresses
		* geolocate - to avoid getting blocked by the census API we need to run with about 4 threads, the dominant time there is building the API request and waiting for it to come back, then the results can be pushed out to the master addresses, and to their children. 
		
* Global considerations:
Some considerations are global, meaning they don't need to be local to a file. 
	* logging is global, and should be driven exclusively by logging_utils.py. An anti-pattern as crept in where each file has its own log_error, log_debug, log_info, etc. 
	* for speed "quiet" is important on debug and info logging so that if quiet is turned on, it won't even bother to prepare for making the log, so you will see numerous if not global_config.quiet statements in the code. It's very much an anti-pattern to have complicated log statements that are built and then discarded. This really only applies to log_debug and log_info statements, as log_error messages and log_warning messages are actually important.
	* global_config.max_files is another important global to know about, this allows us to run with a subset of data for testing.
	* progress information is just as important as logging, so logging_utils.py also maintains a global progress bar.
	* --log-sql turns on logging for the SQL, which is useful for debugging.

	
## Our existing architectural solutions in various phases of implementation
* While normally CRUD applies for a project like this, something I've learned from enterprise is delete is an Anti-pattern you can't recover data once it's deleted. So in enterprise there's only Update, to mark something as deleted. So we're just CRU. Also, we use uuid7 Primary and foreign keys exclusively, so we can build entire object trees in memory and then write them in bulk at our convenience. 
* To deal with the single-writer issue, the read threads should attach their CR and U operations to something called the PendingDatabaseOperation object, which supports a number of DatabaseOperationType calls, and an additional operation that updates the progress bar. Because of the uuid7 primary keys, this is trivial for both operations.
* PendingDatabaseOperation accepts two key methods: addOperationToDatabase used for Updates, and addObjectToDatabase for Creation.
* The progress bar is very important, because for speed we want to run with quiet on unless we're debugging. To that end, PendingDatabaseOperation supports PROGRESS_UPDATE as an operation, which allows the readers to tell the write thread how much they should increment the progress bar after the CR/U operations have been completed. This means the first part of any step is running a select with a count(*) to determine the work to do, and then the processors queue up a PROGRESS_UPDATE operation to update the progress bar.
* irs990processor.py should be as close to a shell as possible, because it should hand off all its work to the various step classes. It's job is to parse the command line arguments, squirrel those values away in config.py and then start the relevant step as defined by --start-step and to stop after --stop-step
* The order for performing operations can be determined by their dataclass in strict onwership order:
	* ZipFile there's 36 of these, they own:
	* XmlFile there's 2.9M of these they create:
	* Charity there's 2.8M of these they create:
		* Grant many of these about 2 per Charity, make some addresses, 1:1 for 990PF files. The main purpose for all this parsing
		* Contractor kind of matches the Charity, 5 max per charity record, have address attached.
		* Contribution not many of those
		* Political_Contribution rare for now
		* Officer many of those, have address attached
	* Addresses we end up with about 4M of those they come in 3 flavors
		* PO Boxes. These can be mapped to a PO Box and a zip, so their colocator field can be calculated at generation time. 
		* Foreign addresses: These are just mapped by country code as defined in countryCodes.py
		* regular addresses: These have a blank colocator field when created, and we have a step that will fill in these addresses via the geolocate step with there latitude and longitude rounded to the nearest 10m. 
	* Address these are made by everything, so they get saved to the database last. 
* ./990tools/models contains all of our dataclass objects that help us manage and encapsulate the data. They have a loose to-one back to their owner define by owner_id and adresss_type, which enables the geolocate step to update their owners colocator field. base.py in that folder holds the base class in order to maintain DRYness.
	* Starting with Charity all objects should be built by their owning object so that the ownership relationship is set properly, and to keep things DRY
* other notes:
	* base_processor.py is supposed to be the base class for all the \_processor.py classes but that's gotten kind of crufty because that idea came later. Ideally, base_processor.py would setup the threadpools, and the progress bar, and the consumer, but its currently a mishmash. There's also this idea of Strategy objects which seems to be duplicating some of the Producer/Consumer split. 
	* while PendingDatabaseOperation works well for the xml step, it hasn't really been integrated into the other producers, which is unfortunate. producer threads should process, produce a PDO, and then the consumer can be simple, it reads the PDO, does the creates in ownership order, then the updates in ownership order, then the progress bar and database optimization updates. Since PDO already has a save_to_database method, that should be used instead of the hard coded ones scatted around throughout the processors. Even the xml step is still mucking about with dictionaries instead of the simple PDO object that encapsulates all that. 
	
## Performance notes:
	* Just like each step has its own best thread count, every step has its own unique optimum batch_size which is seperate and should not be confused with max_files even though they interrelate. We will tweak those per step later, but haven't worried about it now, except the geocoding API can only handle 10000 addresse at a time, and we'll probably lower that to 1000 to make the progress information come more smoothly. Its kind of nerveracking to watch the progress sit there stalled and then update 10000 records. 
