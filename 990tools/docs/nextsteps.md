It's great that performance is so good now, because now we're going to have more stuff happen. 

# Background
So we're following the money, and the people spending the money don't want us to be able to follow it. 
But there is this IRS thing, and people have employees, and the employees need to get paid, which means they get an EIN.
For most grants, the IRS makes charities report what EIN they are sending the grant to. 
* But not for 990pf filers.
* Also, religious organizations and local governments are exempt from filing returns.
However, everyone has to have a mailing address. 
For a long time, I was working on address matching, but that's fussy, I had a bunch of heuristics, was kind of ok. zip_code + po box was dead on accurate. 
But now, with your tax dollars at work, I can match an address to within 10m of each other, which is what the colocator does!
Which means we can:
* Accurately infer organizations who didn't file 990 forms!
* Branch out into tracking 527 orgs, Political Action Committees.

# To Do
* First, we need to set the owner_id in Address for filers as a loose relationship. This will be a theme.
* The geolocate step needs to be multithreaded, with up to 4 API queries feeding into a consumer thread that updates the address records with the colocator, and the Charity record with the colocator as well
* Everything needs to have a colocator field for later matching. If a record of any type has an EIN, great, we'll use that. EIN:<ein>. Otherwise, if we have to match by address, it will generate an address record, and its owner_id will be set, and the address_record will set its address_type based on the owning dataclass.
* Right now, the XML parsing is only creating Address and Officer records, it's not creating Grant, Contractor, or Contribution, or Political Contribution records so we need to add that. 
* We should probably organize the parsing in the order they are in the XML, which is easy, since they're in alphabetical order, Common, ScheduleA-Z. 

# Task
* Multithread the geolocate step using the patterns you learned refactoring the XML processing. There are 11.5K Address records in the database for you to practice on, resist the temptation to use fake data, because the API fails on those. The real data is in /Volumes/Data/final/irs990.duckdb
* Do all the items in the To-Do section, while remembering to be DRY, and follow best coding practices. 

* refactor the code to be DRY, the parse_related entitites probably can go in the base parser rather then being diuplicated
* Look at the files with grep to get an expected count of the related items, and a sense of the XML structure 
* Build a test to make sure the items are getting created, which they aren't currently. 

Colocator format:
  LL:<lat>:<long>  latitude and longitude of the address, these start empty until we geolocate address.
  EIN:<EIN> used for grants that provide an EIN so we don't need to geolocate an Address.
  PO:<po_box>:<zipcode> used for addresses that are PO Boxes. No need to geolocate an address, it would be the post office anyways.
  FA:<countrycode> used for foreign addresses. _
  
  Had to quit, because the process was stuck. 
  
  * In ./990tools you will find a ton of code. 
  * We recently modified the logging in logging_utils.py to include the file name and serial number of the caller. Unfortuantely, there are still still files that aren't using those logging methods.
  
  # Task fix it. 
  * make sure that all logging everywhere has access to the --quiet setting. Logging can drastically impede performance even if it is off, because the code will have to marshall the arguments even if the message won't go anywhere. To this end, every logging block has to check if not args.quiet: so if the quiet is set, there will be zero log impact.
  * While doing that, make sure that logging is all funneled through the master log methods in logging_utils.py. _
  
  Hey dumb question. This code has been massively refactored from old scripts that did each step one at a time, and it is now all driven by irs990processor.py except for a couple of utility scripts and tests. Can you identify the dead scripts? I want to remove them via `git rm` so you don't have to look at them any more. Also, integrate download_irs_990_zips.py into irs990processor.py as a first step "down" in front of step "zips". Run recompress_irs_zips.py in as a step "recompress" after that. The script that finds the best --worker-threads setting is also a keeper: set_worker_threads.py. so is profile_pipeline.py, really any script that calls into irs990processor at a meta level is ok. Don't remove them, just build me a list to review. 
    
    Just realized having you block even log_error calls if --quiet was on was a boo boo, they only run if an error is encountered, which should be rare. So can you change the logic so error and exception logs will still function. 
    
Ok, I want you to start testing. That's pretty easy, just run the pipeline with `timeout 120 python irs990processor.py --verbose --max-files N` this will run it for a maximum of 2 minutes, and you can start N with 16, look for errors in the logs, fix them, try again, until the errors are gone then double N, and gradually increase the 120 second timeout as necessary. The first two steps should do nothing, all the zips are downloaded and recompressed already. Once you processe the first XML file you can add --start-step xmls to skip in the fuuture.  Just loop on your own, I'm going to be out.      

Need to remember to add grants to same place together. 


# Prompt for VSCode Grok Plugin: Refactor Producer-Consumer in XML Processor

You are an expert Python refactoring assistant. Refactor the provided code for a parallel XML processing strategy using the producer-consumer pattern. The code processes IRS Form 990 XML files: producers parse XML files (CPU/I/O-bound), queue results, and a single consumer batches inserts into a DuckDB database (single-writer safe).

## Original Code
[PASTE THE FULL ORIGINAL CODE FROM processing_strategy.py HERE - the entire <DOCUMENT> content]

## Key Requirements & Best Practices
- **Use `queue.Queue`**: Replace `collections.deque` with `queue.Queue(maxsize=QUEUE_SIZE)` for thread-safety. Producers use `put(block=True)` for backpressure; consumer uses `get(block=True)` to block efficiently (no polling or busy-waiting).
- **Signaling**: Each producer sends a `None` sentinel after finishing. Consumer counts `num_producers` sentinels to exit. Use `xml_queue.task_done()` after processing each item, and `xml_queue.join()` in main after producers finish to ensure full drain.
- **Progress Tracking**: Use a small `progress_queue = queue.Queue(maxsize=10)` for consumer to signal batch sizes to main (positive for success, negative for errors). Main tallies `total_processed` from it post-join.
- **Shutdown**: Wait for all producers via `thread.join(timeout=60)` (parse-heavy). Then `join()` queue and consumer (timeout=30).
- **Error Handling**: In consumer, handle `('error', xml_id, msg)` by updating `XmlFiles` table and committing. Wrap batch inserts in try/except; signal errors via progress_queue.
- **Logging**: Reduce verbosity—log per-10/50 files, not per-file. Use class attrs for constants (e.g., `STALL_THRESHOLD=30`).
- **No Changes To**: Keep `_bulk_insert_batch`, `_process_single_xml`, parsing methods, dataclass reflection, dedup logic, and DB ops intact. Don't touch deprecated strategies.
- **Efficiency**: Eliminate all polling loops, stall checks, and `time.sleep()`. Drop tqdm (use simple queue tally). Cap producers at `min(workers, len(files))`.
- **Style**: PEP 8 clean, type hints where possible. Add docs to methods. No magic numbers—extract to attrs.

## Example Refactored Structure (Use as Guide)
Implement similar to this snippet in `ParallelXMLProcessingStrategy`:

```python
import queue
import threading
# ... other imports

class ParallelXMLProcessingStrategy(ProcessingStrategy):
    STALL_THRESHOLD = 30  # Example: Extract magics
    # ... existing attrs

    def execute(self, max_files: Optional[int] = None) -> int:
        xml_files = self._get_xml_files_to_process()
        if max_files:
            xml_files = xml_files[:max_files]
        if not xml_files:
            return 0

        num_producers = min(self.workers, len(xml_files))
        self.log_info(f"Processing {len(xml_files)} files with {num_producers} producers")

        xml_queue = queue.Queue(maxsize=self.QUEUE_SIZE)
        progress_queue = queue.Queue(maxsize=10)

        consumer_thread = threading.Thread(
            target=self._database_consumer,
            args=(xml_queue, progress_queue, num_producers, self.db_ops.db_conn)
        )
        consumer_thread.daemon = True
        consumer_thread.start()

        producer_threads = []
        for i in range(num_producers):
            t = threading.Thread(target=self._xml_producer, args=(xml_files, xml_queue, i, num_producers))
            t.daemon = True
            producer_threads.append(t)
            t.start()

        # Wait for producers
        for i, t in enumerate(producer_threads):
            t.join(timeout=60.0)
            if t.is_alive():
                self.log_error(f"Producer {i} timeout")
            else:
                self.log_info(f"Producer {i} done")

        # Drain queue and consumer
        xml_queue.join()
        consumer_thread.join(timeout=30.0)
        if consumer_thread.is_alive():
            self.log_error("Consumer timeout")

        # Tally progress
        total_processed = 0
        try:
            while True:
                batch_size = progress_queue.get_nowait()
                total_processed += abs(batch_size)
                if batch_size < 0:
                    self.log_error(f"Error in batch of {-batch_size}")
        except queue.Empty:
            pass

        self.log_info(f"Complete: {total_processed} files")
        return total_processed

    def _xml_producer(self, xml_files, xml_queue, producer_id, num_producers):
        processed = 0
        start = producer_id
        for i in range(start, len(xml_files), num_producers):
            xml_id, path, filename, internal = xml_files[i]
            try:
                result = self._process_single_xml(xml_id, path, filename, internal)
                xml_queue.put(result, block=True)
                processed += 1
                if processed % 50 == 0:
                    self.log_info(f"Producer {producer_id}: {processed} queued")
            except Exception as e:
                self.log_error(f"Producer {producer_id} error on {filename}: {e}", exc_info=True)
                xml_queue.put(('error', xml_id, str(e)), block=True)
        xml_queue.put(None)  # Sentinel
        self.log_info(f"Producer {producer_id} done: {processed} files")

    def _database_consumer(self, xml_queue, progress_queue, num_expected, conn):
        batch_data = []
        total = 0
        signals = 0
        while signals < num_expected:
            item = xml_queue.get(block=True)
            if item is None:
                signals += 1
                xml_queue.task_done()
                continue
            if isinstance(item, tuple) and item[0] == 'error':
                xml_id = item[1]
                msg = item[2] if len(item) > 2 else "Error"
                self.db_ops.execute_query(
                    "UPDATE XmlFiles SET processed=TRUE, processing_version=2, error_message=? WHERE xml_id=?",
                    (msg, xml_id)
                )
                self.db_ops.commit()
                xml_queue.task_done()
                continue
            batch_data.append(item)
            total += 1
            xml_queue.task_done()
            if len(batch_data) >= self.BATCH_SIZE:
                try:
                    self._bulk_insert_batch(batch_data, conn)
                    progress_queue.put(len(batch_data))
                except Exception as e:
                    self.log_error(f"Batch error: {e}", exc_info=True)
                    progress_queue.put(-len(batch_data))
                batch_data = []

        # Final batch
        if batch_data:
            try:
                self._bulk_insert_batch(batch_data, conn)
                progress_queue.put(len(batch_data))
            except Exception as e:
                self.log_error(f"Final batch error: {e}", exc_info=True)
                progress_queue.put(-len(batch_data))

        self.log_info(f"Consumer done: {total} items, {signals} signals")

# ... Keep all other methods unchanged


# Some Cleanup
* Remove the dead imports of sqlite that are scattered about. duckdb is so much faster we're never going back, and its dead code.
* We should have dataclass implementations for all database tables. We're missing at least one.
* The aliasing of DC<type> for <type> is probably unnecessary and confusing and should be removed. Review, and remove if not needed. 
* use of placeholders {} and %s in logging strings has been an anti-pattern and makes the code fragile and confusing. Replace them all with modern f strings. This is a tedious cleanup. 
* These stub_log_* methods seem like an anti-pattern. They should either go in logging_utils.py to be DRY, or be eliminated entirely unless you can justify their purpose. Also, the log methods in logging_utils add the file and line number of the caller by using f_back on the frame, and if there are too many wrappers you get the reference to the wrapper not the caller. Maybe need to loop through the frames until you find a function without "log" in the name if these stubs and wrappers are still needed. 
* Passing components of the command line arguments around is tedious, make an args global that can be quickly read instead. This will be especially useful when checking for quiet around logs.
* make sure that pyright is happy with all the .py files needed for irs990processor.py when you're done, don't need to go beyond those.

* ThreadSafeProgressReporter turned out to be an anti-pattern, we can always report progress safely from the consumer thread. Make it gone. 

# Feature Creep
* Processing time is proportional to the size of the XML file, which vary widely. We should collect the size when we're processing the zip file. 
* have an --progress <type> option that determines whether the XML progress is in bytes or files. Default is files.
* Use the Google Knowledge Map API to get URL for photos of all the officers. Docs here: https://developers.google.com/knowledge-graph/reference/rest add a new step "photos" to do this after geocode, and add the database column. Throttle the connections to 1/second, and cache the results in a .json file as you go. 
* Have an option --extract that takes a list of EINs and extracts all of its XML files to a --extract-dest <dir> directory. We can use this to save test XMLs as needed or to pull out problem files. 

* The progress bars seem to be broken again, though the ZIP Files one works, make sure that all the steps update the progress bar in the consumer thread. No thread safety issues with that, since there's only one consumer thread. 

* irs990processor.py has drifted away of its ideal of being mostly a shell, consider moving code out into other files, especially the stats can go into a stats_processor.py file. 
* code to get total size to process near line 198 of processing_strategy.py should just ask for sum(file_size), not get a list and add them up manually python side. 
* Similarly, line 296 in the same file, file_size should be kept around to avoid a database fetch. Ditto for line 360
* optimize_database looks cool, should probably be run after every step completes. 

*  missing a logger? Isn't that a global? ```2025-10-25 14:51:11,901 - ERROR - Failed to process XML 202041299349102209_public.xml: 'NoneType' object has no attribute 'isEnabledFor'
Traceback (most recent call last):
  File "/Users/pierce/Development/datarepublican/990tools/irs990processor.py", line 440, in _process_single_xml
    charity, officers, grants, contractors, contributions = self._parse_990pf_data(root, filename, filer_ein, tax_year, form_type)
                                                            ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/pierce/Development/datarepublican/990tools/irs990processor.py", line 628, in _parse_990pf_data
    charity, officers, grants, contractors, contributions, address = parse_990pf(root, filename, {}, filer_ein, tax_year, form_type, log_error=self.log_error)
                                                                     ~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/pierce/Development/datarepublican/990tools/parse_990pf.py", line 269, in parse_990pf
    total, entries = func(root, field, namespaces, xml_filename, context, xpath_cache, log_error=log_error, xpath_match_stats=xpath_match_stats)
                     ~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/pierce/Development/datarepublican/990tools/parse_990pf.py", line 125, in parse_officer_comp_990pf
    log_info(logger, f"Parsed officer {first_name} {last_name} compensation: ${value} for EIN {context.get('filer_ein', 'Unknown')} in {xml_filename}",
    ~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
             ein=context.get('filer_ein', 'Unknown'))
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/pierce/Development/datarepublican/990tools/logging_utils.py", line 9, in log_info
    if not logger.isEnabledFor(logging.INFO):
           ^^^^^^^^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'isEnabledFor'``` 
* Make sure we're setting the error message on the XMLFile, so we know what happened, supposed to be either the stack trace or a special case 'skipped: 990T', That means updating the 'error' Database Operation to take the message as a param and then passing the message.    


* new warning about consumer thread not being shutdown cleanly after XML processing. 

# We're debugging why the various fields in Address aren't getting saved, which led to finding some deeper problems. 
* Address.py needs a factory method to build an Address record for foreign addresses, they should store "Foreign: {country}" in line1 of the address, (country has to be looked up via the countryCode.py module) and the countryCode in the state field, and FA:countryCode in the colocator field. That should be used by the parse_* code when it finds an <ForeignAddress> tag. 
* the whole idea of passing around lists of address components is broken, and you were supposed to purge it. So line 653:659 are disturbing, the parameters to bulk_insert_addresses should be List[Address]. Also, what happened to our generic bulk insert method that used inspection to get a list of fields? Finally, there are a bunch of single inserts in database_operations.py, some of that is redundant. Bulk insert will work just as well for 1 as it will for 1000.
* All class specific code for prepping a record for insert needs to go in the classes prep_for_insert, all bulk inserts should be generic and just call prep_for_insert on their object (make an abstract superclass for all the model classes if need be) and all bulk_inserts should take a list of the objects they're going to insert.
* In general, database_operations should leverage the OOP concepts and defer all class specific stuff to the model classes. 

Follow up: 
* What is the purpose of the PO_BOX_COLOCATOR_REGEX? If it isn't used, delete it as dead code. Plus you have it in 2 places. 
* bulk_insert should ask the class the necessary field names via a static method, which can calculate it lazily once not every insert. 
* Instead of Any, make an abstract superclass so you know that prep_for_insert always exists, have the superclass implementation make sure the id is generated. I suspect if you do that, you'll find you can just call bulk_insert everywhere, no need to be class specific. Since we're using UUIDs everywhere, that makes both the producer and consumer simple, the producer can simply push all the classes it builds onto a list, the consumer can then sort the list by class type, and call bulk insert on each subset. 
* extract_utils.py is building an Address by passing in a list of address_components, don't do that, just make a full constructor call. 
* the Foreign address factory doesn't look right. Should take the country code; look up everything. The ein has to be looked up from the country code module because they're fake. Use the country_name in the fanme field, can match address line1, i.e. Foreign: {country_name}


database_operations.py:
	* import inspect on line 150 should be top of file. 
	* line 161 should be a log info
	* bulk_insert not as elegant as the old insert_from_dataclass method
	* line 574-620 can all be refactored, I don't think per class bulk-inserts are necessary given that everything is a subclass of ./990tools/models/base.py now. 
	* There needs to be a bulk update operation, we don't need to do a type specific update, its a pretty simple SQL format string: take table name, id, [fields], [values]
	* not sure why _process_charity_operations is necessary given all the generic methods we have now. 
	* _update_xml_file_with_metadata is a perfect example of a case where a generic update method would be just fine and could work in bulk. 
extract_utils.py:
	* I think line 393-426 need to be rewritten to pull each piece of the address out of the address tag with its own XPath, not pulled out en-massse and stacked. Too risky to missassign; you've gone from structured data to a blob.
	* Shouldn't need to call address.prep_for_instert() here, I think that's a hack for logging, or a debugging flail. 
	* similar problem with lines 519-544, you pull structured data into a pile, then try to reverse engineer it. Keep it structured. 
parse_utils.py:
	* Lines 174-189 are the right way to do it, this should be a common function that given an XML element, returns an Address object. 
	* I'm not sure what the backfill stuff in lines 200 are about, we're doing the backfill later on as its own step.
processing strategy.py:
	* import on line 174 needs to be at top of file. 
	* lines 382-452 are all deprecated, can be removed. 
	
xml_processor.py:
	* line 47:62 look sketchy, whatever caused this method to exist should die.
	* _extract_address lines 502:636, where do I begin? First, it should be in one of the parse or extract_utils. 2nd, it makes the address too early, gather everything a piece at a time and then call the constructor. 3rd, the prep_for_insert() is a hail mary from debugging, the generic smart insert stuff we're doing now should call that for us. 

models/address.py:
	* lines 84-96 should be in constants.py not here, and import at the top of the file. 
	* nothing in canonicalize_address can throw an exception, the try/except has never fired and never will. 
	* canonicalize_address is super messy. 
		* If you're going to expand an abbrevation, expand it in place.
		* build parts with parts.append each piece directly from self, and then use a list comprehension to filter out the None: parts= [self.address_line1, self.address_line2...self.zip4] then parts =[p for p in parts if p!= None]
		* canonicalize_address needs to check to see if it has an FA: colocator and if it does, to return without changing the object.   
		
models/xml_file.py:
	* get_xml_files_to_process needs to take a limit param so it doesn't fetch all 2.8M rows to do a batch of 1000. 
	
models/*.py:
	* everything needs to call the prep_for_insert in BaseModel. 
	
	
	
codereview pass 2:
  extract_utils.py:
  	* xpaths in lines-389-440 need to be in one of the xpaths* files. DRY
  	* same thing with liens 562-618, only one place for xpaths, and that's in xpaths*.py
  models/*.py:
  	* don't see the call to the super class prep_for_insert in anything. 
  models/xml_file.py:
  	* get_xml_files_to_process needs to talke a limit param, which needs to be in the SQL, and where that gets called, that needs to be integrated with the batching so it doesn't try to fetch all 2.8M xml ids with a fresh database. This is in processing_strategy.py/def execute at line 110, look through the git history to see the old version of this code. 
  	
codereview pass 3:
  xml_processor.py: 
  _extract_address at line 487-631:
  	1. Shouldn't be in here, it should be in a parse* file, with the XPATHs in a xpaths* file. 
  	2. Also _parse_political_contribution_element from line 633:721, same problem this whould be in parse* with the XPATHS in xpaths*. 
  	3. With no limit passed in from line 110 of processing_strategy.py this will still fetch all 2.8M rows, you have to analyze the batching code in the execute method starting on line 96 of processing_strategy.py. Hint: If you set the limit to the size of the batch, since each batch marks the XML files as being processed, you will get a fresh batch of files.  
  	
# Making the Producer/Consumer model work for us. 
Because only one thread at a time can write to duckdb all of the paralell processing code is split up into a set of Producer threads that pull an XML off the master queue, unzip it parse it, then produce a pile of objects as defined in ./990tools/models. 
The extract and parse utilities then dutifly pass those objects back up through the code tree as tuples. 
This is not the way. It is very tedious to pack everything up in a tuple, then unpack it. Then have the top of the Producer chain queue it for the consumer. We were recently working on adding new types of data to be parsed from the XML files, and we made some progress on that front so we're extracting them as we've confirmed via logs, but they're being dropped on the floor. So we're going to architect our way out of this bug as follows. 
* We will build a class that collects all the objects we wish to eventually pass to the consumer called PendingDatabaseContext. 
	* This has one key method addObjectToDatabase(BaseModel). When that method is called, it will extract the object type name from the object, and add it to lists maintained in a dictionary by object name. Charity objects being a top level object will be stored specially so that any bit of code can say getCharity() to get the charity object. 
	* It has another key method: updateObject(type, id,dictionary). This collects object updates, it will cause the consumer to perform an UPDATE (type) where (type)_id = (id) that takes the keys from the dictionary for the set clause. 
	* This context object will be passed down to each function in the parse tree there is no need to return it, because each level of the parse tree merely adds to the context object. 
	* When all the parsing is done, before returning, the Producer thread can pull the objects out of the context object by type (doing Charity objects first since they own all the others), Addresses generally last because they are generally "owned" by upstream objects. 
	* This will work because we are using UUID7 primary keys, so we pre-wire all the relationships so we're really just dumping entire object trees into the database. 
* While you're refactoring, keep this in mind:
	* It is imperative that XmlFile.error be updated with any failure, so the main routine in the XmlProducer has to catch any exception, and when one occurs, it catches it, extracts the stack trace and error, and updates XmlFile.error with that information. 
	* Add a method "log_it" to the context object that will give a summary of the contents of the object, specifically a count of updates, and inserts by type. 
	
When this work, which will be extensive, is complete, we will be able to produce and save objects to the database at will, and while tedious, this will be less tedious than all the mucking about with logging each stage in the pipeline to see where things are getting dropped. 

## Important info:
* all the code is in ./990tools no need to search all of ./ 
* the real database is in /Volumes/Data/final/irs990.duckdb 
* Once you process and save an XML file to the point of creating a Charity object, you cannot at this time processed it again to save. This is intentional, we're solving the reprocessing step later. 
* There are some sample XML files in ./990tools/test_xmls. If you want more, you can search against the real database to find ideally a collection by form_type and org type, and use unzip against the zip files in /Volumes/Data/irs_zips, and extract them to test_xmls with appropriate names, generally (form_type)_(ein)_(tax_year).xml. Note that the files in ./990tools/test_xmls with "FAIL" in the name are hacked versions of CHAI.xml in that same folder but broken in various ways. 
* You can run the XML portion of the pipeline yourself with --start-step xml --stop-step xml --max-files N that will parse and save N XML files. --verbose will give you the most logs, but you will want to redirect to a file and grep the results in that case, --log-sql is also useful to make sure the SQL is being generated correctly. 


Contractors in 990PF forms:

       <CompensationOfHghstPdCntrctGrp>
          <BusinessName>
            <BusinessNameLine1Txt>RGM CAPITAL</BusinessNameLine1Txt>
          </BusinessName>
          <USAddress>
            <AddressLine1Txt>9010 STRADA STELL CT 105</AddressLine1Txt>
            <CityNm>NAPLES</CityNm>
            <StateAbbreviationCd>FL</StateAbbreviationCd>
            <ZIPCd>34109</ZIPCd>
          </USAddress>
          <ServiceTypeTxt>INVESTMENT MANAGEMENT FEES</ServiceTypeTxt>
          <CompensationAmt>2117470</CompensationAmt>
        </CompensationOfHghstPdCntrctGrp>
        
There were zero political Contributions found when scanning through all 2.8M XML files, however Sierra Club files a schedule C, here is a sample: ```<IRS990ScheduleC documentId="RetDoc1039500001">
<PoliticalExpendituresAmt>963678</PoliticalExpendituresAmt>
<VolunteerHoursCnt>5797</VolunteerHoursCnt>
<Expended527ActivitiesAmt>1552</Expended527ActivitiesAmt>
<InternalFundsContributedAmt>10000</InternalFundsContributedAmt>
<TotalExemptFunctionExpendAmt>11552</TotalExemptFunctionExpendAmt>
<Form1120POLFiledInd>1</Form1120POLFiledInd>
<Section527PoliticalOrgGrp>
<OrganizationBusinessName>
<BusinessNameLine1Txt>MISSISSIPPI SIERRA CLUB PAC</BusinessNameLine1Txt>
</OrganizationBusinessName>
<USAddress>
<AddressLine1Txt>148 OAKHURST TRAIL</AddressLine1Txt>
<CityNm>RIDGELAND</CityNm>
<StateAbbreviationCd>MS</StateAbbreviationCd>
<ZIPCd>39157</ZIPCd>
</USAddress>
<EIN>454833193</EIN>
<PaidInternalFundsAmt>10000</PaidInternalFundsAmt>
</Section527PoliticalOrgGrp>
<SubstantiallyAllDuesNondedInd>1</SubstantiallyAllDuesNondedInd>
<OnlyInHouseLobbyingInd>0</OnlyInHouseLobbyingInd>
<AgreeCarryoverPriorYearInd>0</AgreeCarryoverPriorYearInd>
<SupplementalInformationDetail>
<FormAndLineReferenceDesc>PART I-A, LINE 1:</FormAndLineReferenceDesc>
<ExplanationTxt>SIERRA CLUB PROVIDES ADMINISTRATIVE AND FUNDRAISING SUPPORT TO ITS SEPARATE SEGREGATED FUNDS (SIERRA CLUB POLITICAL COMMITTEE AND SIERRA CLUB VOTER EDUCATION FUND AND STATE POLITICAL ORGANIZATIONS) AND COMMUNICATES WITH ITS MEMBERS AND OTHERS ABOUT CANDIDATES, INCLUDING EXPRESSLY ADVOCATING FOR THEIR ELECTION OR DEFEAT, AS PERMITTED UNDER FEDERAL AND STATE LAW.</ExplanationTxt>
</SupplementalInformationDetail>
</IRS990ScheduleC>``` and you can find their data in ./990tools/test_xmls/SierraClub.xml for testing. This should generate a politicalcontribution records with the name of the orgazation with BusinessNameLine1 and BusinessNameLine2 combined with a space if line2 is present stored in "recipient", with the PaidInternalFundsAmt stored as the Amount, the tax_year from the return, and the associated address record should be built using the build_address factory method. Another one is Alliance.xml in the same directory, their data looks like this: ```<IRS990ScheduleC documentId="RetDoc1039500001">
<PoliticalExpendituresAmt>6000</PoliticalExpendituresAmt>
<VolunteerHoursCnt>0</VolunteerHoursCnt>
<InternalFundsContributedAmt>6000</InternalFundsContributedAmt>
<TotalExemptFunctionExpendAmt>6000</TotalExemptFunctionExpendAmt>
<Form1120POLFiledInd>0</Form1120POLFiledInd>
<Section527PoliticalOrgGrp>
<OrganizationBusinessName>
<BusinessNameLine1Txt>ALLIANCE FOR GUN RESPONSIBILITY VICTORY FUND</BusinessNameLine1Txt>
</OrganizationBusinessName>
<USAddress>
<AddressLine1Txt>PO BOX 4187</AddressLine1Txt>
<CityNm>SEATTLE</CityNm>
<StateAbbreviationCd>WA</StateAbbreviationCd>
<ZIPCd>98194</ZIPCd>
</USAddress>
<EIN>471304996</EIN>
<PaidInternalFundsAmt>6000</PaidInternalFundsAmt>
</Section527PoliticalOrgGrp>
<SupplementalInformationDetail>
<FormAndLineReferenceDesc>PART I-A, LINE 1:</FormAndLineReferenceDesc>
<ExplanationTxt>DONATION TO AGR PAC.</ExplanationTxt>
</SupplementalInformationDetail>
</IRS990ScheduleC>
``` Same thing, pull the EIN, Address, name out and create a Political Contribution record with linked address. 


Ok, the QueueDisplay you implemented is REALLY Cool. Since we have a Producers reading/Consumer writing split in all the steps with thread pools wrapped around the producers, I'd like to have the QueueDisplay on every step so we can see if the Producers are getting too far ahead of the Consumer. So please:
1. Move the QueueDisplay into its only .py file. 
2. Add it to every step from zip through to geocode.
