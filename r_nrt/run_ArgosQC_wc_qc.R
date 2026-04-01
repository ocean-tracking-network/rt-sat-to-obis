require(ArgosQC)
require(jsonlite)

cat("\n\n\n\n")
Sys.time()
cat("\n")

## Read in the config file from the command line.
cli <- commandArgs(trailingOnly=TRUE)
print(cli)


conf <- jsonlite::read_json(cli[1], simplifyVector = TRUE)

wc_qc(wd = ".",
             config = cli[1]
             )
print(getwd())
