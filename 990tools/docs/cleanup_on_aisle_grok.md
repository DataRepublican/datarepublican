read ./memory.md for an overview. 

# Task1: Make logging easier to trace back
So its very tedious to trace a log message back to a particular file and line number. Unfortunately, Python doesn't support __FILE__ and __LINE__ like C does.
* Review every log in the code, and add an abbreviated uuid-7 constant to the long string, so that in the future, you can search for that to get the precise file and line number of the log. 

# Task 2: DRYness is the law
In general, after several iterations on the code, you've gone bezerk and so the code is no longer DRY 
* Every time you copy/paste, you end up duplicating bugs as well. Overhaul all the code to be DRY, import as much as possible, and make every file have a single, well defined purpose.
* The distinction between a processor and a strategy is lost on me, and it keeps confusing you. We probably need to consolidate the processors and the strategy, since they seem to be 1:1. 
* Add a docstring to the top of every file declaring it's purpose, and to every class so you can read it, put GROK/KORG around sections for you in the future. 