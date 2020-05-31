# Proportional Reader

## Purpose

TBC

## How it works

TBC

## Things to do

### Should do now
### Things Remaining
[ ] Compare to POCDriver for a similar number of threads
[ ] Run a couple of proper tests
[ ] Write up a readme.md


#### Future work
[ ] Look at using a scheduler or similar to start the execution (rather than while less than loop)
[ ] Do some analysis on how much execution workload could overload the response handling workload (if realistic at all)... some back pressure isn't an issue however the queue will fill at 30k
    - consider moving the responsetime calculation (i.e. (end - start).totalsecs) from the query execution into the results handler (less work for query exec to do)
[ ] Look at using 'pools (mulitprocessing)' to do the query execution