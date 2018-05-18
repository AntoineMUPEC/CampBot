# CampBot

Bot framework for camptocamp.org

## Installation

```batch
    pip install campbot
```

## Command line usage

### Export recent contribution

This command will load all contributions made in the last 24 hours

```batch
    campbot contributions
```

Optional arguments : 

* `-starts=2017-12-07` : will export all contributions after this date (included)
* `-starts=2017-12-07` : will export all contributions before this date (excluded)
* `--out=data.csv` : out file name, default value is `contributions.csv`


### Check recent changes
Check that last day modifications pass these tests : 
  
* History is filled
* No big deletions
* And all patterns present in the first message of topic where report should be posted

```batch
campbot check_rc --login=<login> --password=<password> [--delay=<seconds>]
```
  
  
### Check poll voters

Check that voters in a poll forum has at least one contribution during last 180 days

```batch
campbot check_voters <message_url> --login=<login> --password=<password>
```

<message_url> is the url of the massage that contains the poll you need to check



