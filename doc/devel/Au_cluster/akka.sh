#!/bin/bash
### SNAC project number, enter if applicable.
### NOTE! No spaces or slashes allowed
#PBS -A HPC2N-2008-005
### Requesting 64 nodes with 8 VP:s on each node
#PBS -l nodes=64:ppn=8
### Requesting time - 40 minutes
#PBS -l walltime=00:40:00

# Change to Working Directory
cd $PBS_O_WORKDIR

module add openmpi/1.2.6/gcc

gpawhome=${HOME}/gpaw
export PYTHONPATH=${gpawhome}:${PYTHONPATH}
mpiexec ${gpawhome}/build/bin.linux-x86_64-2.4/gpaw-python ../Au_cluster.py --sl_diagonalize=5,5,64 --gpaw=usenewlfc=1
