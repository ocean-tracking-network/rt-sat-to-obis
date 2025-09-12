require(ArgosQC)
require(jsonlite)

cat("\n\n\n\n")
Sys.time()
cat("\n")

## Read in the config file from the command line.
cli <- commandArgs(trailingOnly=TRUE)
print(cli)


conf <- jsonlite::read_json(cli[1], simplifyVector = TRUE)

## create required dirs if not exist
## TODO: Get these directories from the config file.

# output.dir
if(!dir.exists(conf$setup$output.dir)) dir.create(conf$setup$output.dir)

# data.dir
if(!dir.exists(conf$setup$data.dir)) dir.create(conf$setup$data.dir)

# maps.dir
if(!dir.exists(conf$setup$maps.dir)) dir.create(conf$setup$maps.dir)

# diag.dir
if(!dir.exists(conf$setup$diag.dir)) dir.create(conf$setup$diag.dir)


cid <- conf$harvest$cid # TODO - get this from the config file.

print(paste0('Operating on ',cid))

smru_qc(wd = ".",
             config = cli[1]
             )


print(getwd())


## This function expects a pwd variable that we don't have, so it causes errors.
## Zip output QC files, do not push to AODN
# push_2_aodn(
#  cid = cid,
#  path = "aodn",
#  nopush = TRUE,
#  suffix = "_nrt"
#)

