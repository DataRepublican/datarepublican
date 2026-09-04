# Reviewing the latest round of changes
base_parser.py:_
	* Dangling problem context['filer_ein'] is now an anti pattern, when you can use context.getCharity().ein
	* parse_form in base_parser.py is still returning a bunch of tuples, which makes me not trust you. 
	* parse_form in base_parser.py is still assembling lists of things, which again, not necessary, just add them as you go. 
	* Also, it should be the master parse_form object that builds the Charity object, no need for that code to be repeated in parse990, parse990ez, parse990pf. Then we have to fix problems 3x. 
pending_datbase_context.py:
	* I didn't see where the PendingDatabaseContext object generates the appropriate bulk_update and bulk_insert calls? Probably should be a method in pending_database_context that given a database operations object, makes the appropriate calls. Call it "save_to_database(DatabaseOperations connection)"
	* Which reminds me we should store the XML_file and xml contents in the pending context for easy access, less to pass down. Tedious seeing "root" everywhere. 

* database_operations.py
	* lines 711-735, I think this code can go mostly, it was there to debug why charities weren't getting saved.
	* lines 1092 this can be pulled out, you were under the mistaken assumption that the tax_year had something to do with why something wasn't working when the reality was that grans weren't even being parsed. 
	* lines: 1063-1171, Come to think of it, the whole _process_related_operations method is moot now as the new context object handles it. 
	* lines: 1166-1173, another moot method, the database context handles updates. 
* irs990processor.py:
	* lines 594-638: Moot, these functions should build and store the Contractor objects and squirrel them away in the context.
	* lines 651-659: this probably shouldn't be here, irs990processor should just extract the XML, then pass it off to the master parse_form with a database context. The only thing it needs to deal with is updating the XmlFile with the appropriate data: tax_year, EIN, form_type, processed=true, processing_version, and catching any exception and updating the error message and status fields appropriately. 
* parse_990.py
	* line: 193 Never bury imports in a method, they should live on the top of the file always. Pet peeve. 
	* line: 197-201: this local_context object is bad, it's ok temporarily, but once the Charity is built, everything should be in there. 
	* lines: 218-220: The filer_name is f"{business_name_line_1}{if business_name_line_2: business_name_line2 else: ""} no need to keep them seperate, just concatenate them. 
	* lines 240-245: This structure is fine for the single field entries, but for the object creation, better to just have them added to the pending context. That means you extract the officers AFTER building the Charity object. You should probably add a factory method on Charity that builds one for you so you can get the charity_id anyways.
	* lines 252-268: The denominator should be pulled via the total income for a charity. this is quickly available in the <CYTotalRevenueAmt> XML tag. This should be stored in the denominator column.
	* lines 247: take abs(value) as the numerator in the division. Clamp percentages to -1, 101. People spend more than their income if they're spending down their assets.
	* line 266-267: This should be available in the XML file. 
	* line 307-315: Parse should do this. 
	* line 318: Parse should just have add the address to the context itself, no need to return it. Add a factory method on to Charity that builds the address if it doesn't have one already. 
	* line 322-329: Again, no need to unpack from tuples, the parse functions can add them to the context on their own. 
* parse_990ez.py:
	* line 323-336: No need for *_legacy should be able to collapse this code into one method
	* same issues as previously, you're still collecting data, then looping to create the objects, Just make them one at a time, making factory methods as needed on Charity, Officer, etc. 
	* line 469-475: again with the *_legacy? Needs to go away. 
parse_990pf.py:
	* same criticism as the other two parsers:
		* build the Charity before it gets to this method in parse_form using the feedback from parse_990.py_
		* don't collect data, then build objects from a list, just add the object as you go.
		* add factory methods to the owning classes where necessary
		* In general, the main differences between the 3 format types are:
			* grants never have EINs in 990pf files, just addresses. 
			* some schedules never happen in 990/ez/pf so no point in looking for them, but you'll have to research which make sense. 
			* maybe some header differences? 
		* lines 391-397: more legacy bullshit, kill it. 
parse_utils.py:
	* lines: 114-191: too many print statements, imports buried in code, and you should never pass an exception, re-raise it so the top of the tree will log the exeption against the XmlFile object. 
	* lines: 245-344: I need to dig up some 990s with a Schedule C. Anyways, same pattern of building data then appending it to a list and returning the list, at least there was some nod to adding it to the context instead. 
processsing_strategy.py:
	* line 99: buried import
	* line 126: ditto
xml_processor.py:
	* line 87-115: I'm thinking that there should be a method in parse_utils that immediately grabs the form_type, tax_year, ein, and org_type from the file, then schedules and xml_update to set that information in the pending context. if there's an exception during parsing, it can add another XML_update to set the status, processed and error fields seperately, if not, then it adds another update method to do that. 
	
# Code Review #2:
Please keep this list around, and in your final response, list the status of each item instead of summarizing and then only doing half the items. It's annoying. In fact, do that for the first code review before reading this one. Let me know if you need me to repeat it. 
First, some information about the different form types:
	* 990 Form 990 has the broadest set of schedules (A through R), with 16 main ones. These are required if the organization answers "Yes" to certain checklist questions in Part IV of the form.
	* Form 990-EZ uses a subset of the Form 990 schedules (primarily A, B, C, E, G, L, N, O), plus a few others like M and R in specific cases. These are triggered by similar "Yes" answers in Part V.
	* Form 990-PF (for private foundations) differs significantly—it doesn't use most lettered schedules like 990/990-EZ. Instead, it requires detailed supporting schedules (often line-specific attachments) for Parts I–XVI, plus Schedule B if applicable. These provide breakdowns of income, expenses, assets, and compliance. Section 4947(a)(1) trusts may also need Schedule A.
Information about the schedules: (IGNORE means we don't care)
	* A Reports public charity status and public support tests (e.g., donor and government support percentages).
	* B (IGNORE) Lists major contributors (gifts of $5,000+ or 2% of total contributions).
	* C Details political campaign and lobbying activities, including expenditures.
	* D (IGNORE) Provides supplemental financial statements (e.g., endowments, conservation easements, donor-restricted assets).
	* E (IGNORE) Reports operations as a school, including nondiscrimination policies.
	* F Describes activities and grants outside the U.S. (e.g., foreign program services).
	* G (IGNORE) Covers fundraising events, professional solicitors, and gaming (e.g., bingo).
	* H (IGNORE) Details hospital facilities, community benefits, and health needs assessments.
	* I Lists grants/assistance to U.S. organizations, governments, or individuals (> $5,000).
	* J Reports compensation for officers, key employees, and top earners (> $150,000).
	* K (IGNORE) Provides info on tax-exempt bonds (e.g., private use, arbitrage).
	* L (IGNORE) Discloses transactions with interested persons (e.g., loans to officers).
	* M (IGNORE)
	* N (IGNORE) Reports liquidation, termination, or major asset dispositions (>25% of net assets).
	* O (IGNORE) Supplies narrative explanations for form responses (e.g., program descriptions).

Implications: I think we need to saddle up and make the parse_*.py files into class objects, base_parser should pull the major fields from the top of the form, create the Charity object, then based on form_type call out to the right subclass. We'll make a stub class for 990T that just creates an XmlFile update to set status to skipped 990T. 


* base_parser.py:
	line 195: in general, for parsing, better to fail by re-raising the exception after logging it. What we'll end up doing in xml_processor.py is catching the exception and not only updating XmlFile status and errormessage, but also saving the XML contents to a folder for later perusal, say ./990tools/broken_xmls then you can iterate on all the broken XMLs for later. 
	line 261-271: No need to add to list just add to the context, and there should be a factory method on Grant that builds the address for you. 
	line 355: anywhere I see you returning lists, I know you haven't properly refactored. 	_	line 401: buried import
	line 409: I think you have a chicken/egg problem here, I don't think the Charity has been built or added yet to the context. You're updating the charity fields, but that won't work unless you either add an update call to the pending context. So revamp all of this to collect the information from the top of the form, then build the Charity object, then build the associated Address object using the factory in the Charity, then start parsing other stuff. 
* database_operations.py:
	* line 68, 96, 97 all this per-class quiet and log_sql is buggy as shit. self.quiet sucks, so does self.log_sql. Just read it live from global_config.log_sql, no need to copy it around into every class. 
	* line 705 looks wrong. Too many params to getattr
	* line 711-735: This stuff can just go. If we need pre-save validation and debugging, we can put it into pending_database_context.py
	* line 794-801: print instead of logs. 
	* line 1093: more bogus tax_year checks I think I told you about the first time.
	* line 1084-1164: All this code is dead now, because the parsers insert the objects for you into the context. 
	* line 1166-1182: This is too specific, just needs to build an update and add it to the context. 
irs990processor.py
	* line 464-660: None of this stuff belongs here:
		* parse/extract methods to grab single fields, ok, but put it in parse_utils_
		* _extract_xml_from_zip_cache is ok, it can stay but it should be in xml_processor.py not here, same with the zip cache. _
		* _profile_xml_processing should probably be calling some method shouldn't have the same code in 2 places for looping over the XML files in batches.
parse_990.py:
	* line 198+ Still has the local_context, but that should all be in context.getCharity() already, which should be done by the higher level parse function 
	* line 271-329 general comment, still building the Charity object here, nope. The structure on line 222-236 of having the list of fields to pull is good, but that can be generic, and for things that spawn objects like the officer comp, that's a seperate parse task anyways. so I'm kind of disappointed because I feel like I told you this already. 
parse_990ez.py:
	* line 334: I still see an _legacy method, so I know you're an idiot. 
	* line 469-475: ditto
parse_990pf.py:
	* line 260: There's legacy again. How many times do I have to tell you know? Are you sure you know what the word refactor means?
parse_utils.py:
	* line 116-191: need to make the print statements log_info statements. Should call a factory method on Charity to build the grant line 182. buried import line 181, need to handle the no-EIN so grabbing the address case. 
	* line 232: buried import, alo, should be using a factory method on Charity to build the Political contribution object so it gets the charity_id, etc. 
	* line 263-310: XPaths live in the xpath* files, period. Move them there, and add the appropriate import to the TOP of the file, not buried down here. 
	* line 334, 344: adding to a list and returning it is bad. 
processing_strategy.py:
	* line 99: buried import, top of file. 
	* line 126: buried import, top of file
	* line 362: self.quiet instead of global_config.quiet 
xml_processor.py:
	* Same comments as from previous review. 
	* lines 192-198: this will be replaced by a single call to our form parser class
	* lines 204-213: this can all go. 
	* lines 220: Unnecessary, built by the form parser. 
	* lines 214-282: whereever the code is that spins of the pending_database_context into the bulk_insert and bulk_update calls should do this, not the xml_processor. Think I told you this in the first review. 
	* lines 287-335: Don't belong in xml_processor, methods in base_parser.py
	* lines 336-356: will be part of the new parse classes, see list of schedules by form type, 990pf being the tricky one.
	* lines 428-586: None of this code belongs in xml_processor, it should be handled by the parse classes. 
	* line 605: there is no possible utility for having self.processing_version, just grab the global constant.
	* line 607-652: This should be context aware, you don't need to sort the operations by type, that's already done for you by the context. And probably, the context should be able to do all this work give a DatabaseOperations object, or have the DatabaseOperations object take a context object, six-of-one to be honest. 
	* line 788-810: DatabaseOperations supports a bulk_update call, this should use that.
	
xpaths.py:
	* no real comment just that you should know that the xpaths work by trying different things in order, first one that matches wins, you can add broadly with no cost. 

models:
	charity.py:
		line 28-31: this should be after the fields at line 68, not in the middle. 
		line 134-139: Need to pass self.charity_id to the PoliticalContribution constructor
	zip_file.py:
		line 58-62: this should be handled by the BaseModel now. 
	
# Code Review #3
Please keep this list around, and in your final response, list the status of each item instead of summarizing and then only doing half the items. It's annoying.  Let me know if you need me to repeat it at any time. My doing code reviews is a kindness, do not abuse me being nice. Yes its more work, but just like I would tell any junior engineer, this is how you learn.  

base_parser.py:
	lines 152, 159: import lines from parse_utils should be at top of file, not here.
	* Add a factory method that from an XML file, pulls out all the useful info, builds the right subclass by form_type of the parser, builds a charity object and adds it to the context, then returns the parser only. _
database_operations.py:
	line 756: still references self.log_sql instead of global_config.log_sql
	line 917-1018: old approach, just remove _process_related_operations entirely, the pending context object does this now. 
irs990processor.py:
	lines 60-64: importing parse functions immediately points to cruft, irs990processor.py is just a shell for farming out work to steps. 
	lines 408-812: None of this XML specific stuff should be here, it should all be in xml_processor.py
680005486:
	680005486: All special cases for EIN 680005486 need to be eliminated across all the parse modules. 

parse_990.py:
	lines 205-216: form_type is passed in, so all this code lokos unnecessary
	lines: 218: Isn't the filer name generated earlier? 
	lines: 222-245: Pulling in the fields is fine, but officers come in from a schedule
	lines: 247-250: See one of the code reviews about finding the total_income, using it for the denominator, and claiming percentages to -1-101. 
	lines: 270-304: this should be built upstream, not here. 
	lines: 306-315: these are a schedule parse, and should be using a factory method to build the Offiser record. 
	lines: 317: this should be done upstream when the Charity object gets built. 
	lines: 322-329: Yeah, no, shouldn't be getting done here, should be done by the parsers for the schedules. 
parse_990ez.py:
	line 323: Now that we have classes for this, there should be just one parse_form method, and then the subclasses override it. 
	line 337: *_legacy is the pattern his refactor is getting rid of. 
	line 349: This sholud be happening upstream. 
	line 362-364: This should be happening upstream. 
	line 365-480: see previous comments for parse_990.py, same problem
parse_990pf.py:
	No point in reviewing, hasn't been turned into a class yet. 
parse_utils.py:
	lines 41-63: Which schedule is this parsing? is this dead code?
    lines: 114-194: This shouldn't be here, this should be in parse_schedule_i which sholud live in parse_schedlue_i.py and it should add Grant and Address objects to the context. 
    lines: 196-243: same as for grants, but parse_schedule_c.py
    lines: 245-344: same as for parse_contributions, but parse_schedule_L,also, the XPaths need to be in xpath*.py
    lines: 385-584: move to parse_schedule_c if needed. 
	_	
processing_strategy.py:
	lines: 99: imports always on top of file. 
	lines: 363: self.quiet instead of global_config.quiet
xml_processor.py:
	line: 79: try/except block, except catches exception and updates the XML File. 
	line 195-201: Shouldn't need an if on form_type, the base parser has a factory method that will build the correct parser for you, and it will build the charity object as well, so all you need here is parser.parse_form(xml_content,context)
	lines 207-218: just delete this, we'll log that stuff elsewhere. 
	line: 222-224: this is another good place to catch any processing exceptions and update the XML file
	line 225-279: Not the right place for this, in fact, delete it, already in save_to_database in pending_database_context. 
	line 333-366: form specific parsing? No. OOP. Delete. 
	line 423-629: None of this stuff belongs here anymore, delete. 
	line 842-858: We have a generic bulk_update in database_operations.py, use that.
	line 861+: I quote ```XML Processor - Legacy wrapper for backward compatibility.

    DEPRECATED: This class is maintained for backward compatibility.
    New code should use XMLProducer and XMLConsumer classes directly.``` Yeah, just delete that whole thing. backward compatibility is an outdated concept with AI. 
    
code review #4:
Please keep this list around, and in your final response, list the status of each item instead of summarizing and then only doing half the items. It's annoying.  Let me know if you need me to repeat it at any time. My doing code reviews is a kindness, do not abuse me being nice. Yes its more work, but just like I would tell any junior engineer, this is how you learn.  
xpaths.py: I see that you've changed things to find the Schedule as the root, good. 
xml_processor.py:
	* line 859-EOF: 
		This legacy wrapper is dead code, remove it. No, wait, I'll do it for you. Done. 
	* many other lines: Just deleting stuff you shouldn't need anymore bacause its in a parse module somewhere. Go scan it to see what remains. I'll leave it to you to patch any dangling references. 
	* search the code base (./990tools/*.py) for all references to tax_year > 2020 and delete any related code. 
	* line 219: Don't just catch the exception, update the XmlFile with the exception. _
processing_strategy.py:
	* line 101: through out codebase replace self.quiet with global_config.quiet this is just one example. Make sure to add the relevant import to the TOP of the file
	* line 126: buried import, move to top of file. 
parse_utils.py:
	removing all the parse_schedule stubs, because we'll be calling them from the subclasses not here. Useles code. 
parse_990pf.py:
	* Still not a subclass of base parser?
parse_990ez.py:
	* not a subclass of base parser? 
parse_990.py:
	good this at least is a subclass. 
	* line 68-78 these should be parse_schedule_f parse_schedule_I calls. 
	* line 79-> get_field_parsers I'm punting on the stuff that was parsing schedule_O it was crap. We get the totals from the top of the form, we'll trust them for now. Deleted, rescan file. 
	* parse_form ok, that reads in the balance sheet from the top. Eventually we need it to call the relevant parse_schedule() methods too. 
	line: 155-169 (line after deletions) OK, you make a bare Parser990() then there's a special parse_990 method... Oh, that's to support main(). Yeah, not necessary, the factory method in base_parser should build the right thing. 
irs990processor.py: Clean, looks good. 
database_operations.py: Clean, looks good. 
base_parser.py: This will be the test!
	line 357: This should be a stub here, with concrete implementations in parse_990 and parse_990ez that call the parse_schedule_xx methods that are appropriate to their type. 
		Reminder: Looks like we only care about I/C for both, and L is for loans not contractor. PF is done by "parts" they don't have schedules. 
	line 340: As a practical matter, I think this method should know enough about how to extract the form type, and such itself, then create a Charity object and add it to the context for us, along with some XMLFile updates. BTW, there is no parse_990T file. _
	line 209-330: ok, this is the basic function everythign calls. Base parser needs some of this to be in parse_header, it parses the XML and setup the charity object in the context, can build it mostly with None, then it can make the appropriate class of parser_ and have that parser finish the header parsing (990PF are a special case so we have to go through the subclass). Let me rephrase that. Integrate the header parsing here with the factory on line 340 so that it parses enough of the file to know the form type, and other information, and can build the charity and update the XmlFile with size and form_type and org_type. It then returns the proper parse class back to xml_procesor which will then call parse_form with a context to get the rest of the information. 
	* Hmmm.. this needs some serious rework, but I'm kind of tired but its not very OOPy and this is a very OOPy problem, 4 different form types, etc. I'll leave it for later and I have to research how 990PF files will work. 
pending_database_context.py:
	save_to_database: Make sure we have constructors for grant, constructor, political_contribution objects in Charity, and make sure Grant, Contractor, PoliticalContribution objects have an Address factory 
	the lines that set the owner_id to the charity shouldn't be necessary, thats why we have the factories
	db_ops.insert_charity can just be db_ops.bulk_insert([self._charity]). 
	Make the bulk insert all objects take a list of keys, and then call db_ops.bulk_insert on them in that order. 
	
	
	
	Contractors XML: <q>
<ContractorName>
<BusinessName>
<BusinessNameLine1Txt>MADWOLF TECHNOLOGIES</BusinessNameLine1Txt>
</BusinessName>
</ContractorName>
<ContractorAddress>
<USAddress>
<AddressLine1Txt>818 CONNECTICUT AVE NW 950</AddressLine1Txt>
<CityNm>WASHINGTON</CityNm>
<StateAbbreviationCd>DC</StateAbbreviationCd>
<ZIPCd>20006</ZIPCd>
</USAddress>
</ContractorAddress>
<ServicesDesc>IT SERVICES</ServicesDesc>
<CompensationAmt>922401</CompensationAmt>
</ContractorCompensationGrp>

Things we need to do in the geolocation_processor:
* easy: 
	* batch_size being passed into the constructor is an anti-pattern, instead make a new step specific constant in constants.py, and remove the value from the constructor. 
	* Bump the number of addresses in a request up to 10000, the census docs are pretty specific that this is fine. New constant in constants.py for this. 
	* add more logging so I can tell what's going on in this debugging period, following the pattern of using global_config.is_quiet before the log calls so it won't impact performance if we don't want it to.
* harder: 
	* progress bar still not showing. 
* hardest: 
	* Acknowledge the 2 step split by having the producer threads act on both types of work: addresses that need a geolocation record, and geolocation records that need to be looked up via the API. Probably makes sense to do two queries and merge the results into one queue by wrapping each work unit into a holding class MASTER_ADDRESS_TASK, or CENSUS_ADDRESS_TASK. That makes the producers job simple, it knows exactly what it should do. We probably need 2 thread pools, one for the Geolocation records and another for the API lookups, I would expect the Geolocation threads to complete early, and then the API lookups to lag. So the API thread pool would be 4 max, while the fast thread pool 
	* Consumer then gets new operations: SAVE_GEOLOCATION to create Geolocation records which it can do using bulk insert, or UPDATE_GEOLOCATION after the API completes, which it can do using buik_update. 	
	* Need to store the result code in the Geocoding.geocoding_status which is generaly Match, No_Match, or Tie, we're just storing "failed","success" at this point. 


Hang: 

============================================================
Stack traces for 3 threads (PID: 49638)
Signal: 30 at Thu Oct 30 10:17:52 2025
============================================================


Thread: Thread-6180270080 (ID: 0x1705f7000)
  File "/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/lib/python3.13/threading.py", line 1012, in _bootstrap
    self._bootstrap_inner()
  File "/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/lib/python3.13/threading.py", line 1041, in _bootstrap_inner
    self.run()
  File "/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/lib/python3.13/threading.py", line 992, in run
    self._target(*self._args, **self._kwargs)
  File "/Users/pierce/Development/datarepublican/990tools/geolocation_processor.py", line 517, in _producer_worker
    operations = producer._process_work_batch(batch)
  File "/Users/pierce/Development/datarepublican/990tools/geolocation_processor.py", line 125, in _process_work_batch
    geocoding_result = self._geocode_address(first_address)
  File "/Users/pierce/Development/datarepublican/990tools/geolocation_processor.py", line 211, in _geocode_address
    results = cg.addressbatch(batch_addresses)
  File "/Users/pierce/.python3/lib/python3.13/site-packages/censusgeocode/censusgeocode.py", line 250, in addressbatch
    return self._post_batch(data=data, **kwargs)
  File "/Users/pierce/.python3/lib/python3.13/site-packages/censusgeocode/censusgeocode.py", line 219, in _post_batch
    with requests.post(url, data=form, timeout=kwargs.get("timeout"), headers=headers) as r:
  File "/Users/pierce/.python3/lib/python3.13/site-packages/requests/api.py", line 115, in post
    return request("post", url, data=data, json=json, **kwargs)
  File "/Users/pierce/.python3/lib/python3.13/site-packages/requests/api.py", line 59, in request
    return session.request(method=method, url=url, **kwargs)
  File "/Users/pierce/.python3/lib/python3.13/site-packages/requests/sessions.py", line 589, in request
    resp = self.send(prep, **send_kwargs)
  File "/Users/pierce/.python3/lib/python3.13/site-packages/requests/sessions.py", line 703, in send
    r = adapter.send(request, **kwargs)
  File "/Users/pierce/.python3/lib/python3.13/site-packages/requests/adapters.py", line 667, in send
    resp = conn.urlopen(
  File "/Users/pierce/.python3/lib/python3.13/site-packages/urllib3/connectionpool.py", line 787, in urlopen
    response = self._make_request(
  File "/Users/pierce/.python3/lib/python3.13/site-packages/urllib3/connectionpool.py", line 464, in _make_request
    self._validate_conn(conn)
  File "/Users/pierce/.python3/lib/python3.13/site-packages/urllib3/connectionpool.py", line 1093, in _validate_conn
    conn.connect()
  File "/Users/pierce/.python3/lib/python3.13/site-packages/urllib3/connection.py", line 790, in connect
    sock_and_verified = _ssl_wrap_socket_and_match_hostname(
  File "/Users/pierce/.python3/lib/python3.13/site-packages/urllib3/connection.py", line 969, in _ssl_wrap_socket_and_match_hostname
    ssl_sock = ssl_wrap_socket(
  File "/Users/pierce/.python3/lib/python3.13/site-packages/urllib3/util/ssl_.py", line 480, in ssl_wrap_socket
    ssl_sock = _ssl_wrap_socket_impl(sock, context, tls_in_tls, server_hostname)
  File "/Users/pierce/.python3/lib/python3.13/site-packages/urllib3/util/ssl_.py", line 524, in _ssl_wrap_socket_impl
    return ssl_context.wrap_socket(sock, server_hostname=server_hostname)
  File "/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/lib/python3.13/ssl.py", line 455, in wrap_socket
    return self.sslsocket_class._create(
  File "/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/lib/python3.13/ssl.py", line 1076, in _create
    self.do_handshake()
  File "/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/lib/python3.13/ssl.py", line 1372, in do_handshake
    self._sslobj.do_handshake()


Thread: Thread-6163443712 (ID: 0x16f5eb000)
  File "/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/lib/python3.13/threading.py", line 1012, in _bootstrap
    self._bootstrap_inner()
  File "/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/lib/python3.13/threading.py", line 1041, in _bootstrap_inner
    self.run()
  File "/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/lib/python3.13/threading.py", line 992, in run
    self._target(*self._args, **self._kwargs)
  File "/Users/pierce/Development/datarepublican/990tools/geolocation_processor.py", line 589, in _consumer_worker
    operation = operation_queue.get()
  File "/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/lib/python3.13/queue.py", line 202, in get
    self.not_empty.wait()
  File "/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/lib/python3.13/threading.py", line 359, in wait
    waiter.acquire()


Thread: Main (ID: 0x20c77e0c0)
  File "/Users/pierce/Development/datarepublican/990tools/irs990processor.py", line 642, in <module>
    main()
  File "/Users/pierce/Development/datarepublican/990tools/irs990processor.py", line 620, in main
    action()
  File "/Users/pierce/Development/datarepublican/990tools/irs990processor.py", line 555, in <lambda>
    "geolocate": lambda: processor.geolocate_addresses(),
  File "/Users/pierce/Development/datarepublican/990tools/irs990processor.py", line 451, in geolocate_addresses
    return self.geolocation_processor.geolocate_addresses()
  File "/Users/pierce/Development/datarepublican/990tools/geolocation_processor.py", line 698, in geolocate_addresses
    producer_thread.join()
  File "/opt/homebrew/Cellar/python@3.13/3.13.2/Frameworks/Python.framework/Versions/3.13/lib/python3.13/threading.py", line 1092, in join
    self._handle.join(timeout)
  File "/Users/pierce/Development/datarepublican/990tools/processing_strategy.py", line 326, in dump_threads_handler
    stack_lines = traceback.format_stack(frame)

============================================================

	
Code Review Notes:
* You deprecated ParallelXMLProcessingStrategy why not the others in processing_strategy.py?
* with many threads, the USR1 signal handler is a key function and should probably be in base_processor.py so everyone gets it
* all processors 
	irsfetch_processor.py
	zip_processor.py
	xml_processor.py
	address_deduplication_processor.py
	geocoding_api_processor.py geolocation_processor.py (one of these is redundant)
	stats_processor.py we run this after every step so we get a dump of what happened so not strictly a step but useful. 
	
Code Review #2:
xml_processor.py is the only processsor refactored
do we need strategies in processing_strategy.py? Is everything now in base_processor.py and the _processor.py subclasses?
* Migrate all of these, not just xml_processor.py:
	* irsfetch_processor.py
	* zip_processor.py
	* xml_processor.py
	* address_deduplication_processor.py
	geocoding_api_processor.py geolocation_processor.py (one of these is redundant)
	stats_processor.py we run this after every step so we get a dump of what happened so not strictly a step but useful. 
_

Code Review #3
address_deduplication_processor.py:

	lines_ 230-233 build a geocoding record, 
	line 235 makes a new one with no information?
	object is never actually passed to context?
base_processor.py:
	You seem to be having this idea of collecting multiple contects, and some processors should not use PendingDatabaseContext, but that's not true, and a PDC is already an aggregator. Each thread should return one context, and contexts already accumulate operations, so there's no need for them to return multiple. Rather a thread should generate one PDC, then return that to the master, which will put them on the queue for collection by the consumer thread. 

pending_database_context.py:
	This should have a class method that takes a list of PDC objects, merges the operations by type, and then executes the inserts, then the updates as the architecture describes calling save_to_database on the combined PDC. This will let the consumer threads grab a batch of thes PDCs, merge them for efficiency. All other consumers that are writing to the database directly should be refactored to simply called save_to_database here. 


Code Review #4: 

pending_database_context.py:
	The merge is only keeping the first charity, with this change where we merge PDCs, it not necessary to only keep one, so we should maintain the list of all charities, and hope the upstream code is honest. 
address_deduplication_processor.py:

	lines_ 230-233 build a geocoding record, 
	line 235 makes a new one with no information?
	object is never actually passed to context?

geocoding_api_processor.py:
	why is the queue size on the thread pools only 10? Also there should be 4 producer threads, not 1. 
irsfetch_processor: is still using a data dictionary instead of a ZipFile factory. 
_ 	
	
	
Next:
in database_opeerations, right now, we have a whole bunch of very specific INSERT_type methods which then call our bulk_insert method. Refactor that to remove all of them in favor of the GENERIC_INSERT method that accepts a pile of objects to insert, organizes them by class type, and calls bulk_insert on each object in the ownership order from the Architecture.md file. Make another operation called INSERT_BY_TYPE that takes a list and a type, but doesn't have to sort before being calling bulk_update for use by the DatabasePendingContext, since the DPC has already sorted all the objects by type when added. 

Code Review #5:
address_deduplication_processor:
	* lines 229-239: Slightly weird behavior to create and Address objects just to use its factory method to build a geocoding object. Perhaps refactor fetch to return Address objects instead of canonical_addresses We have a select that does that.
	* lines 244-250: Still using the legacy INSERT_ should just be context.addObjectToDatabase()
	* _process_operations_batch() this is very specific to this particular consumer, can't we do most of this with execute_contexts_batch in the base class?
	* irsfetch_processor.py: Since this only downloads and recompresses, there's no longer an operation for you to add to the context. Perhaps this should be refactored to be producer only, so move the file processing code into the producer
	* xml_processor: still has stuff to process operations, PendingDatabaseContext does all this now
	* zip_processor: Don't need processor specific handling of operations, just have the producer build the right objects, then call addObjectToDatabase(object) on the PendingDatabaseContext
	* models/address.py imports line 226-227 need to move to top of file. 
	
	
Code Review #6:
	address_depublication_processor.py:
		* still see it inserting GeoCoding records line 383 PendingDatabaseContext should do that. 
	base_processor.py:
		* execute_context_batch: 
			Inxtead of doing the contexts one at a time, use the PDC merge function to 
			create a master PDC, then calle save_to_database with the single master. 
	database_operations.py:
		* remove all the INSERT_TYPE DatabaseOperationType methods since we now use INSERT_BY_TYPE and this will force us to refactor the dead code. lines 41-47, 58
	pending_database_context:
		still treats charity object as special, no need just append it to self._objects like any other object type. This simplifies merge as well
		save_to_database sill assumes only one charity, but should be treating charity like any other object typle, (i.e. a list)
		save_to_database also uses GENERIC_INSERT, but it can use INSERT_BY_TYPE because the type is the key the objects are stored under. 
		execute_update_geocoding isn't implemented. update_address_geocoding in database_opertions does this but it needs the address_id of the relevant address so that has to be part of the operation. 
	xml_processor.py:
		XML_FILE_UPDATE operation is still needed though you don't have to loop over the operations, just add an update operation with the file_size and form_type.
		
		
Code Review Friday AM:
* You moved the conference XPaths to xpaths.py, but I see multiple form types in there. This is bad. form_type governs the XPaths, that's why we have an xpaths file per form_type, because once you now the form type, you can optimize to only use the appropriate Xpaths. please refactor those into files by type and load them from there. The files are: 
	* xpaths.py universal xpaths, like address parsers, etc. 
	* xpaths_990.py xpaths specific to 990 forms. 
	* xpaths_990ez.py xpaths specific to 990ez forms.
	* xpaths_990pf xpaths specific to 990pf forms. 990pf forms are the red-headed stepchild of forms, very much legacy, very much a problem but a large portion of the money in NGOs comes from them. 

CR Continued: 
Read the file ./990tools/Architecture.md and extract the key instructions related to the project structure, XPath handling, and any refactoring guidelines. Provide a concise summary of the instructions that should be followed for this task. This subtask should only perform the reading and summarization as outlined, and signal completion using attempt_completion with a thorough summary of the extracted instructions.

then complete the following code review items:
database_operations.py:
	* lock on write is a perferred multi-processing strategy, and locks are death on performance. DatabaseOperations._table_metadata_lock is unnecessary, its filled at startup, and never changed. Probably don't need an @lru_cache either, there's not that many tables. Don't need the fallback either just log and sys.exit(-100). So refactor all uses of that in that file appropriately.
	* _get_table_name doesn't need an lru_cache ether, not that many tables. 
	* Audit use of DatabaseOperations._zip_cache_lock it only gets written when we load a new zip file. 
	* The 100000 batch size constant at line 992 should be a constant in constants.py
	* make the charity de-dup check starting at line 1044 controlled by a command-line parameter, its only needed in extremis. 
base_processor.py:
	* don't need complicated set events, that's all locks. Just setup global flags called self.exit_processing, have the signal handlers set that flag to True, check the flag inside the producer and consumer, print("Exiting thread"). False -> True is foolproof. Probably can go in base_processor right after the call to _process_work_batch_to_context on line 338. And set it in line 400, check it after line 411. Maybe that will fix why we're not getting profile information reliably. 
	_
xml_processor.py:
	* still see a content cache line 64? Makes no sense, we load an XML, we parse it, we throw it away. remove ALL OF THAT. Audit the whole file. 
	

Other thoughts:


Code Revew #7:
	adresss_depulication_processor.py:
		lines 254->260 can be replaced with context.addObjectToDatabase(geocoding)
		_process_operations_batch I think is dead code? PDC should do this?
		_
		
big refactor code review:
	address_depuplication_processor.py:
		* Still see self.producer.shutdown_event.is_set()
		
	xml_processor.py:
		* still referencing timeout_event. 
		
		

		
		
Ok, we've done a big refactor of the code, and we made it through all the steps to xml, but then we hit a snag with the producer/consumer model. We worked through it, but we need the following 3 thread set architecture which is now implemented in the xml_processor:
	* A feeder thread fetches data from the database. It then slices that data up into small pieces, packages them inside a WorkQueueUnit that has 3 types of work units. 
		* sentinel: A sentinel work unit encodes the number of the producer thread, that tells the producer that there is no more work. When the feeder runs out of work, it puts one of these in the work queue for each producer. Producers handle this kind of work unit by checking to see if it belongs to them. If it doesn't it puts it back in the queue. If it does match, it passes it along to the result_queue and exits. _
		* xml_file: this is the basic work data for a producer, producers take these items, work on them, collect the data into a PendingDatabaseContext, wrap that PDC into a 'result' unit, and place it in the result_queue. Producers increment a thread-safe counter to tell the consumer thread how many of these to expect in the result_queue
		* result: A result work unit wraps a PendingDatabaseContext, the consumer thread collects however many there are in the result_queue, merges them, and executes them en-masses. 
	* the work_queue is bounded in size, so essentially the feeder thread will automatically block when the consumer and producer threads are busy. The consumer thread rolls up work results in batches of 100, so its pretty efficient at saving to the database. 
	* So the thread sets are:
		* the feeder thread
		* the producer ThreadPool
		* the consumer thread

So the next task is to:
	1. Generalize the architecture in xml_processor up into base_processor so everything is more OOPy. It was tricky to get all this code working, so it would be nice if subclasses merely had to implement _feed_thread, _producer_thread_, and can probably use the base class consumer thread, since we've standardized on PendingDatabaseContext the pattern.  
	2. Make sure xml processor still runs by doing a few `timeout 120 python irs990processor.py --max-files 105 `. `select count() from Charities` against '/Volumes/Data/final/irs990.duckdb' should show an increase after each run, and it shouldn't deadlock. 
	3. Port address_deduplication_processor.py to the new architecture. 