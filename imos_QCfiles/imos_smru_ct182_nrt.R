require(ArgosQC)

cat("\n\n\n\n")
Sys.time()
cat("\n")

## create output dir if not exist
if(!dir.exists("aodn")) dir.create("aodn")


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

