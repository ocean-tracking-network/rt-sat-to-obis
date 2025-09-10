require(ArgosQC)

cat("\n\n\n\n")
Sys.time()
cat("\n")

## Read in the config file from the command line.
cli <- commandArgs(trailingOnly=TRUE)
print(cli)



## create required dirs if not exist
if(!dir.exists("aodn")) dir.create("aodn")
if(!dir.exists("mdb")) dir.create("mdb")
if(!dir.exists("maps")) dir.create("maps")
if(!dir.exists("diag")) dir.create("diag")


cid <- "ct188"
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

