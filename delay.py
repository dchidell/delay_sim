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
# usage: delay.py [-h] [-s] [-v] [-f] [-i] [-o] [-d DELAY] [-c | -t] Interrupt Map
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
##################################

import argparse
import subprocess
import yaml
import json
import random

def main():
    args = parse_args()


    try:
        with open(args.yaml,'r') as f:
            configuration = yaml.load(f)
    except FileNotFoundError:
        print('Error: File {} not found!'.format(args.yaml))
        exit(1)

    ##########################################
    # Hardcoded customisation (changes very rarely - if ever)
    #interfaces = {'enp7s0': 'enp7s0', 'enp6s0': 'enp6s0'}
    #interface_core_mapping = {'eth0-tx': 30,
    #                          'eth0-rx': 10,
    #                          'eth1-tx': 10,
    #                          'eth1-rx': 30}
    #delay = '10ms'
    #queues = 8
    # End of customisation section
    ##########################################

    for group in configuration['interface_groups']:
        delay = configuration['interface_groups'][group]['delay']
        queue_count = configuration['interface_groups'][group]['queue_count']
        interface_list = list(configuration['interface_groups'][group]['members'].keys())


        interface_core_mapping = dict()
        for interface in configuration['interface_groups'][group]['members']:
            for suffix in configuration['interface_groups'][group]['members'][interface]:
                if suffix not in ('tx','rx'):
                    print('Error: only "tx" and "rx" should be present under interface members!')
                    exit(1)
                interface_core_mapping['{}-{}'.format(interface,suffix)] = configuration['interface_groups'][group]['members'][interface][suffix]

        sim = DelaySim(interface_list, interface_core_mapping, configuration['kernel_tweaks'], delay, queue_count, args.state)
        sim.set_show(args.show)
        sim.set_verbose(args.verbose)
        sim.set_force(args.force)

        if args.setup:
            sim.initial_setup()
        elif args.teardown:
            sim.teardown_setup()

        if args.output:
            sim.process_irq_values(configure=False,show_existing=False)  # Show new stuff
            sim.process_irq_values(configure=False,show_existing=True)  # Show existing stuff

        if args.irq and not(args.teardown):
            sim.process_irq_values(configure=True)  # Configure valies

    #try:
    #    interface_core_mapping = dict()
    #    mapping_string = args.map.strip()
    #    interface_map= mapping_string.split(',')
    #    for interface in interface_map:
    #        key_value = interface.split(':')
    #        interface_core_mapping[key_value[0]] = int(key_value[1])
    #except Exception:
    #    print('Error: Unable to parse mapstring! String: {}'.format(args.map.strip()))
    #    exit(1)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Configures the Linux OS to process delay-simulator parameters.',
        epilog='Written and developed by David Chidell (dchidell@cisco.com) & Reece Hanham (rehanham@cisco.com)')

    parser.add_argument('-s', '--show', action='store_true',
                        help='Show information only - do not execute.')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Increase verbosity.')
    parser.add_argument('-f', '--force', action='store_true',
                        help='Force operation.')
    parser.add_argument('-y', '--yaml', default='delay.yml',
                        help='YML config file.')
    parser.add_argument('-a', '--state', default='.delay_state.json',
                        help='Delay state file. No need to edit manually.')             
                    
    parser.add_argument('-i', '--irq', action='store_true',
                        help='Configure static IRQ values.')
    
    parser.add_argument('-o', '--output', action='store_true',
                        help='Output existing IRQ values.')

    parser.add_argument('-d', '--delay',default='10ms',
                        help='Delay value (as used by tc) Default is 10ms')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('-c', '--setup', action='store_true',
                       help='Run setup.')
    group.add_argument('-t', '--teardown', action='store_true',
                       help='Teardown setup (rebooting will do the same).')
    return parser.parse_args()


class DelaySim():
    show_only = False
    verbose = False
    force = False

    def __init__(self, interfaces, interface_core_mapping, kernel_tweaks, delay, queues, state_file):
        self.interfaces = interfaces
        self.interface_core_mapping = interface_core_mapping
        self.delay = delay
        self.queues_per_interface = queues
        self.kernel_tweaks = kernel_tweaks
        self.state_file = state_file
        self.state = dict()
        self.read_state()


    def set_show(self, show):
        self.show_only = bool(show)

    def set_verbose(self, verbose):
        self.verbose = bool(verbose)

    def set_force(self, force):
        self.force = bool(force)

    def delete_state(self):
        for interface in self.interfaces:
            self.state.pop(interface,None)
        self.save_state()

    def save_state(self):
        state_string = json.dumps(self.state)
        with open(self.state_file,'w') as f:
            f.write(state_string)

    def read_state(self):
        try:
            with open(self.state_file,'r') as f:
                data = f.read()
                self.state = json.loads(data)
        except FileNotFoundError:
            self.state = dict()

        bridge_id = random.randint(10,100000)  
        if self.verbose:
            print('Generating bridge IDs...')
            print('Bridge ID: {}'.format(bridge_id))
            print('Interfaces: {}'.format(','.join(self.interfaces)))

        for interface in self.interfaces:
            if self.state.get(interface,None) is None:
                self.state[interface] = bridge_id

    def teardown_setup(self):
        if self.is_setup_done() is False:
            print('Bridge interface is not detected!!!')
            if self.force is False:
                return
            print('Force enabled proceeding anyway!!!')

        if self.show_only:
            print('SHOWING CONFIGURATION ONLY! Performing no actual config...')
        print('Bringing down hw interfaces...')
        for interface in self.interfaces:
            self.process_external_command(
                'ifconfig {hw_interface} down'.format(hw_interface=interface))
        print('Removing tc delay queues...')
        for interface in self.interfaces:
            for queue in range(1, self.queues_per_interface + 1):
                try:
                    self.process_external_command('tc qdisc del dev {hw_interface} parent :{queue} netem delay {delay} limit 1000000'.format(
                        hw_interface=interface, queue=queue, delay=self.delay))
                except ValueError as e:
                    print(
                        'Warning: Unable to remove tc configuration - possibly it never existed! Detail: {}'.format(e))
        print('Removing bridge interfaces...')
        self.process_external_command('ifconfig br{} down'.format(self.get_bridge_id()))
        self.process_external_command('brctl delbr br{}'.format(self.get_bridge_id()))
        self.delete_state()
        print('Torn down!')

    def initial_setup(self):
        # This should *really* be done inside a bash script - but this is good enough.
        if self.is_setup_done():
            print('Bridge interface detected...assiming initial setup is complete!')
            if self.force is False:
                return
            print('Force enabled proceeding anyway!!!')

        if self.show_only:
            print('SHOWING CONFIGURATION ONLY! Performing no actual config...')
        print('Killing irqbalance...')
        try:
            self.process_external_command('killall irqbalance')
        except ValueError as e:
            print(
                'Warning: Unable to kill irqbalance - perhaps it is dead? Detail: {}'.format(str(e)))

        print('Bringing up hw interfaces...')
        for interface in self.interfaces:
            self.process_external_command(
                'ifconfig {hw_interface} 0.0.0.0 promisc up'.format(hw_interface=interface))
        print('Creating and configuring bridge groups...')
        self.process_external_command('brctl addbr br{}'.format(self.get_bridge_id()))
        for interface in self.interfaces:
            self.process_external_command(
                'brctl addif br{} {hw_interface}'.format(self.get_bridge_id(),hw_interface=interface))
        self.process_external_command('ifconfig br{} up'.format(self.get_bridge_id()))
        print('Tuning CPU...')
        self.process_external_command('cpufreq-set -r -g performance')
        print('Tuning kernel values...')
        for tweak in self.kernel_tweaks:
            self.process_external_command(
                "echo '{}' > /proc/sys/{}".format(self.kernel_tweaks[tweak], '/'.join(tweak.split('.'))))
        print('Using tc to add delay queues...')
        try:
            for interface in self.interfaces:
                for queue in range(1, self.queues_per_interface + 1):
                    self.process_external_command('tc qdisc add dev {hw_interface} parent :{queue} netem delay {delay} limit 100000'.format(
                        hw_interface=interface, queue=queue, delay=self.delay))
        except ValueError as e:
            print(
                'Warning: Unable to add tc configuration - does it already exist? Detail: {}'.format(e))
        self.save_state()
        print('All configured!')

    def process_irq_values(self, configure=False,show_existing=False):
        with open('/proc/interrupts', 'r') as file:

            # This dict stores a mapping of interface to current core number
            interface_irq = dict.fromkeys(self.interface_core_mapping, 0)
            if configure:
                print('Configuring IRQ values...')
            else:
                print('Displaying proposed new IRQ mappings...')

            for line in file:
                for interface in interface_irq:
                    if interface in line:
                        elements = line.strip().split(':')
                        if len(elements) < 2:
                            raise ValueError

                        core = self.interface_core_mapping[interface]
                        counter = interface_irq[interface]
                        bitmask = self.corenum_to_bitmask(core + counter)

                        if show_existing:
                            print("cat /proc/irq/{}/smp_affinity".format(elements[0]))
                        else:
                            if configure:
                                self.process_external_command(
                                    "echo '{}' > /proc/irq/{}/smp_affinity".format(bitmask, elements[0]))
                            else:
                                print('Interface: {}-{} IRQ: {} Core: {} Mask: {}'.format(
                                    interface, counter, elements[0], core + counter, bitmask))

                        #print("echo '{}' > /proc/irq/{}/smp_affinity".format(bitmask,elements[0]))
                        

                        interface_irq[interface] += 1
                        # Current loop only needs to run once.
                        break

    def get_bridge_id(self):
        bridge_list = list(set(self.state[idx] for idx in self.interfaces))
        if len(bridge_list) > 1:
            print('Error: Detected multiple bridge-IDs in a single instance....delete file {} and try again.'.format(self.state_file))
            print(self.state)
            exit(1)
        return bridge_list[0]
            

    def is_setup_done(self):
        process = subprocess.run(['ifconfig', 'br{}'.format(self.get_bridge_id())],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        response = True if process.returncode == 0 else False
        return response

    def process_external_command(self, cmd):
        if self.show_only:
            print(cmd)
        else:
            if self.verbose:
                print(cmd)
            command_list = cmd.split(' ')
            if command_list[0] == 'echo':
                # We need to handle echo commands a bit different...
                # 0 = 'echo'
                # 1 = content
                # 2 = '>'
                # 3 = filename
                #print(command_list)
                with open(command_list[3],'w') as fileh:
                    fileh.write(command_list[1].replace("'",''))
                    print('Wrote {} to file {}'.format(command_list[1],command_list[3]))
            else:    
                r = subprocess.run(
                    command_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if r.returncode != 0:
                    raise ValueError(r.stderr)
                else:
                    print('Command executed successfully! Command: {}'.format(cmd))

    def corenum_to_bitmask(self, core):
        if core > 64 :
            raise NotImplementedError

        # Calculate the bit mask for the cores.
        bitmask = hex(1 << core)[2:]

        # Convert to format suitable for /proc/interrupts
        if len(bitmask) < 9:
            bitmask = '0' * 8 + ',' + bitmask.rjust(8, '0')
        else:
            bitmask = bitmask.rjust(16, '0')
            bitmask = bitmask[0:8] + ',' + bitmask[8:16]
        return bitmask


if __name__ == "__main__":
    main()
