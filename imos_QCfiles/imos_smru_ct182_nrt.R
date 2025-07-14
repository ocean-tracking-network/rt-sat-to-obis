require(ArgosQC)

cat("\n\n\n\n")
Sys.time()
cat("\n")

## create required dirs if not exist
if(!dir.exists("aodn")) dir.create("aodn")
if(!dir.exists("mdb")) dir.create("mdb")
if(!dir.exists("maps")) dir.create("maps")
if(!dir.exists("diag")) dir.create("diag")


cid <- "ct182"
imos_smru_qc(wd = ".",
             config = "config_ct182.json"
             )


## Zip output QC files, do not push to AODN
push_2_aodn(
  cid = cid,
  path = "aodn",
  nopush = TRUE,
  suffix = "_nrt"
)

