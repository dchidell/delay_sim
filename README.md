# delay_sim
#!/usr/bin/python3
# Author: David Chidell (dchidell)

#################################
# This script will configure a UCS server running Ubuntu Linux to introduce delay between two physical network interfaces.
# Most options are specified via the CLI. Run this script with the --help option to find more.
# Some configuration is hardcoded. Check 'Hardcoded customisation' section within the main function
#################################
# **The following is performed as a result of this script:**
#
# * Physical initiation of HW interfaces (including promiscuous mode)
# * L2 bridge interfaces (via brctl) configured between the two HW interfaces
# * CPU optimisation tuned using 'cpufreq-set'
# * Various kernel tweaks for allocating memory etc
# * 'tc qdisc' commands executed to add delay between interfaces
##################################
# **Script Requirements:**
#
# The following tools must be installed at an OS level:
#
# * python3 (To run this script!)
# * brctl (apt-get install bridge-utils)
# * cpufreq-set (apt-get install cpufrequtils)
# * tc (Should come with the kernel)
#
#
# The Cisco VIC adapter should be configured via CIMC to have the following configured:
#
# * 8 TX Queues
# * 8 RX Queues
# * Recieve Side Scaling enabled
# * 256byte TX & RX buffer size per queue
##################################
# **The following python modules are required:**
# * argparse
# * subprocess
#################################
# **Usage:**
# usage: irq.py [-h] [-s] [-v] [-f] [-i] [-o] [-d DELAY] [-c | -t] Interrupt Map
# 
# Configures the Linux OS to process delay-simulator parameters.
# 
# positional arguments:
#   Interrupt Map         This is the interrupt mappings for the ethernet
#                         interfaces to CPU cores. Example:
#                         'eth0-tx:10,eth0-rx:30,eth1-tx:30,eth1-rx:10'
# 
# optional arguments:
#   -h, --help            show this help message and exit
#   -s, --show            Show information only - do not execute.
#   -v, --verbose         Increase verbosity.
#   -f, --force           Force operation.
#   -i, --irq             Configure static IRQ values.
#   -o, --output          Output existing IRQ values.
#   -d DELAY, --delay DELAY
#                         Delay value (as used by tc) Default is 10ms
#   -c, --setup           Run setup.
#   -t, --teardown        Teardown setup (rebooting will do the same).
# 
# Written and developed by David Chidell (dchidell@cisco.com) & Reece Hanham
# (rehanham@cisco.com)
##################################
# **About this script:**
#
# Written by David Chidell (dchidell@cisco.com)
# Contributions by Reece Hanham (rehanham@cisco.com)
# Traffic Engineering Research conducted by David Chidell and Reece Hanham.
#
# This script belongs to Solution Validation Services @ Cisco UK
