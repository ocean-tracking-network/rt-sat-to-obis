#!/bin/bash
cd ~/projects/rt-sat-to-obis/input/

for f in *; do
  if [ -d "$f" ]; then
    cd $f
    # Find the config file in this folder
    # or quit
    for config in $(ls ./config_*.json);
    do
    
    # test the offload for new data somehow?
    
    # run the script using the config file
      echo "Running ArgosQC with ${config}"
      Rscript '../run_ArgosQC.R' $config  > "${config}.log" 2>&1

    # run the Python DwC and publishing script
      fp=`readlink -f $f`
      echo "Publishing the resulting archive to your OBIS IPT"
      /home/jdpye/miniconda3/envs/rt-sat/bin/python '../../convert_argosqc_to_dwc.py' "${fp}" >>"${config}.log" 2>&1
    done
    cd ..
  fi
done