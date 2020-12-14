#!/usr/bin/env python3
# Copyright 2020 Efabless Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Reads in a structural verilog containing pads and a LEF file that
contains at least those pads and produces a DEF file with the padframe.
TODO:
core placement
config init,
external config
"""
import os
import sys
import random
import argparse
from subprocess import Popen, PIPE, STDOUT

import opendbpy as odb

# TECH = ""
# PDK_ROOT = os.environ["PDK_ROOT"]
# os.environ["MAGTYPE"] = "maglef"

parser = argparse.ArgumentParser(
    description='Generates a padframe DEF')

# required if -cfg is not specified
parser.add_argument('--verilog-netlist', '-verilog',
                    help='A structural verilog containing the pads (and other user macros)')

parser.add_argument('--def-netlist', '-def',
                    help='A DEF file containing the unplaced pads (and other user macros)')

parser.add_argument('--design', '-d',
                    help='Name of the top-level module')

parser.add_argument('--width',
                    help='Width of the die area')

parser.add_argument('--height',
                    help='Height of the die area')


parser.add_argument('--output-def', '-o',
                    required=True,
                    help='Name of the output file name')

parser.add_argument('--padframe-config', '-cfg',
                    help='CFG file -- input to padring')

parser.add_argument('--pad-name-prefixes', '-prefixes',
                    default=['sky130_fd_io', 'sky130_ef_io'],
                    help='e.g., sky130_fd_io')

parser.add_argument('--init-padframe-config', '-init', action='store_true',
                    default=False,
                    help='Only generate a CFG file to be user edited')

parser.add_argument('--working-dir', '-dir',
                    default=".",
                    help='Working directory to create temporary files needed')

parser.add_argument('--special-nets', '-special',
                    nargs='+',
                    type=str,
                    default=None,
                    help='Net names to mark as special')

parser.add_argument('--lefs', '-l',
                    nargs='+',
                    type=str,
                    default=None,
                    required=True,
                    help='LEF input')

args = parser.parse_args()

verilog_netlist = args.verilog_netlist
def_netlist = args.def_netlist
design = args.design
width = args.width
height = args.height
config_file_name = args.padframe_config
output_file_name = args.output_def
init_padframe_config_flag = args.init_padframe_config
working_dir = args.working_dir
lefs = args.lefs
special_nets = args.special_nets
pad_name_prefixes = args.pad_name_prefixes

working_def = f"{working_dir}/{design}.pf.def"
working_cfg = f"{working_dir}/{design}.pf.cfg"

for lef in lefs:
    assert os.path.exists(lef), lef + " doesn't exist"


def invoke_padring(config_file_name, output_file_name):
    print("Invoking padring to generate a padframe")
    padring_command = []
    padring_command.append('padring')
    for lef in lefs:
        padring_command.extend(['-L', lef])
    padring_command.extend(['--def', output_file_name])
    padring_command.append(config_file_name)

    p = Popen(padring_command,
              stdout=PIPE,
              stdin=PIPE,
              stderr=PIPE,
              encoding='utf8'
              )

    output = p.communicate()
    print("STDERR:")
    print('\n'.join(output[1].splitlines()[-10:]))
    print("STDOUT:")
    print(output[0].strip())

    print("Padring exit code:", p.returncode)
    assert p.returncode == 0, p.returncode
    assert os.path.exists(output_file_name)

# hard requirement of a user netlist either as a DEF or verilog
# this is to ensure that the padframe will contain all pads in the design
# whether the config is autogenerated or user-provided
assert verilog_netlist is not None or def_netlist is not None, "One of --verilog_netlist or --def-netlist is required"

# Step 1: create an openDB database from the verilog/def using OpenSTA's read_verilog
if verilog_netlist is not None:
    assert def_netlist is None, "Only one of --verilog_netlist or --def-netlist is required"
    assert design is not None, "--design is required"

    openroad_script = []
    for lef in lefs:
        openroad_script.append(f"read_lef {lef}")
    openroad_script.append(f"read_verilog {verilog_netlist}")
    openroad_script.append(f"link_design {design}")
    openroad_script.append(f"write_def {working_def}")
    # openroad_script.append(f"write_db {design}.pf.db")
    openroad_script.append(f"exit")

    p = Popen(["openroad"],
              stdout=PIPE,
              stdin=PIPE,
              stderr=PIPE,
              encoding='utf8'
              )

    openroad_script = '\n'.join(openroad_script)
    # print(openroad_script)

    output = p.communicate(openroad_script)
    print("STDOUT:")
    print(output[0].strip())
    print("STDERR:")
    print(output[1].strip())
    print("openroad exit code:", p.returncode)
    assert p.returncode == 0, p.returncode
    # TODO: check for errors
else:
    assert def_netlist is not None
    working_def = def_netlist

assert os.path.exists(working_def), "DEF file doesn't exist"

db_top = odb.dbDatabase.create()
# odb.read_db(db_top, f"{design}.pf.db")
for lef in lefs:
    odb.read_lef(db_top, lef)
odb.read_def(db_top, working_def)

chip_top = db_top.getChip()
block_top = chip_top.getBlock()
top_design_name = block_top.getName()

print("Top-level design name:", top_design_name)


## Step 2: create a simple data structure with pads from the library
# types: corner, power, other
pads = {}
libs = db_top.getLibs()
for lib in libs:
    masters = lib.getMasters()
    for m in masters:
        name = m.getName()
        if m.isPad():
            assert any(name.startswith(p) for p in pad_name_prefixes), name
            print("Found pad:", name)
            pad_type = m.getType()
            pads[name] = pad_type
            if  pad_type == "PAD_SPACER":
                print("Found PAD_SPACER:", name)
            elif pad_type == "PAD_AREAIO":
                # using this for special bus fillers...
                print("Found PAD_AREAIO", name)
        if m.isEndCap():
            # FIXME: regular endcaps
            assert any(name.startswith(p) for p in pad_name_prefixes), name
            assert not m.isPad(), name + " is both pad and endcap?"
            print("Found corner pad:", name)
            pads[name] = 'corner'

print()
print("The I/O library contains", len(pads), "cells")
print()

assert len(pads) != 0, "^"

## Step 3: Go over instances in the design and extract the used pads
def clean_name(name):
    return name.replace('\\', '')

used_pads = []
used_corner_pads = []
other_instances = []
for inst in block_top.getInsts():
    inst_name = inst.getName()
    master_name = inst.getMaster().getName()
    if inst.isPad():
        assert any(master_name.startswith(p) for p in pad_name_prefixes), master_name
        print("Found pad instance", inst_name, "of type", master_name)
        used_pads.append((inst_name, master_name))
    elif inst.isEndCap():
        # FIXME: regular endcaps
        assert any(master_name.startswith(p) for p in pad_name_prefixes), master_name
        print("Found pad instance", inst_name, "of type", master_name)
        print("Found corner pad instance", inst_name, "of type", master_name)
        used_corner_pads.append((inst_name, master_name))
    else:
        assert not any(master_name.startswith(p) for p in pad_name_prefixes), master_name
        other_instances.append(inst_name)

# FIXME: if used_corner_pads aren't supposed to be instantiated
assert len(used_corner_pads) == 4, used_corner_pads

print()
print("The user design contains", len(used_pads), "pads, 4 corner pads, and", len(other_instances), "other instances")
print()
assert len(used_pads) != 0, "^"

## Step 4: Generate a CFG or verify a user-provided config

def chunker(seq, size):
    l = [seq[i::size] for i in range(size)]
    # sort by type
    l.sort(key=lambda pad_pair: pad_pair[1])
    return l

def diff_lists(l1, l2):
    return (list(list(set(l1)-set(l2)) + list(set(l2)-set(l1))))

def generate_cfg(north, east, south, west, corner_pads, width, height):
    cfg = []
    cfg.append(f"AREA {width} {height} ;")
    cfg.append("")


    assert len(corner_pads) == 4, corner_pads
    cfg.append(f"CORNER {corner_pads[0][0]} SW {corner_pads[0][1]} ;")
    cfg.append(f"CORNER {corner_pads[1][0]} NW {corner_pads[1][1]} ;")
    cfg.append(f"CORNER {corner_pads[2][0]} NE {corner_pads[2][1]} ;")
    cfg.append(f"CORNER {corner_pads[3][0]} SE {corner_pads[3][1]} ;")

    cfg.append("")

    for pad in north:
        cfg.append(f"PAD {pad[0]} N {pad[1]} ;")

    cfg.append("")

    for pad in east:
        cfg.append(f"PAD {pad[0]} E {pad[1]} ;")

    cfg.append("")

    for pad in south:
        cfg.append(f"PAD {pad[0]} S {pad[1]} ;")

    cfg.append("")

    for pad in west:
        cfg.append(f"PAD {pad[0]} W {pad[1]} ;")

    return '\n'.join(cfg)


if config_file_name is not None:
    assert os.path.exists(config_file_name), config_file_name + " doesn't exist"
    with open(config_file_name, 'r') as f:
        lines = f.readlines()
    user_config_pads = []
    for line in lines:
        if line.startswith("CORNER") or line.startswith("PAD"):
            tokens = line.split()
            assert len(tokens) == 5, tokens
            inst_name, master_name = tokens[1], tokens[3]
            if not pads[master_name] == "PAD_SPACER" and not pads[master_name] == "PAD_AREAIO":
                user_config_pads.append((inst_name, master_name))
        elif line.startswith("AREA"):
            tokens = line.split()
            assert len(tokens) == 4, tokens
            width = int(tokens[1])
            height = int(tokens[2])

    assert sorted(user_config_pads) == sorted(used_pads+used_corner_pads),\
        ("Mismatch between the provided config and the provided netlist. Diff:", diff_lists(user_config_pads, used_pads+used_corner_pads))

    print("User config verified")
    working_cfg = config_file_name
else:
    # TODO: get minimum width/height so that --width and --height aren't required
    assert width is not None, "--width is required"
    assert height is not None, "--height is required"

    # auto generate a configuration

    # TODO: after calssification, center power pads on each side
    north, east, south, west = chunker(used_pads, 4)

    with open(working_cfg, 'w') as f:
        f.write(generate_cfg(north, east, south, west, used_corner_pads, width, height))

if not init_padframe_config_flag:
    invoke_padring(working_cfg, working_def)
else:
    print("Padframe config generated at", working_cfg,
          f"Modify it and re-run this program with the '-cfg {working_cfg}' option")
    sys.exit()

print("Applying pad placements to the design DEF")

db_padframe = odb.dbDatabase.create()
for lef in lefs:
    odb.read_lef(db_padframe, lef)
odb.read_def(db_padframe, working_def)

chip_padframe = db_padframe.getChip()
block_padframe = chip_padframe.getBlock()
padframe_design_name = block_padframe.getName()

assert padframe_design_name == "PADRING", padframe_design_name

print("Padframe design name:", padframe_design_name)

# Mark special nets
if special_nets is not None:
    for net in block_top.getNets():
        net_name = net.getName()
        if net_name in special_nets:
            print("Marking", net_name, "as a special net")
            net.setSpecial()
            for iterm in net.getITerms():
                iterm.setSpecial()

# get minimum width/height (core-bounded)

placed_cells_count = 0
created_cells_count = 0
for inst in block_padframe.getInsts():
    assert inst.isPad() or inst.isEndCap(), inst.getName() + " is neither a pad nor corner pad"

    inst_name = inst.getName()
    master = inst.getMaster()
    master_name = master.getName()
    x, y = inst.getLocation()
    orient = inst.getOrient()

    if (inst_name, master_name) in used_pads + used_corner_pads:
        original_inst = block_top.findInst(inst_name)
        assert original_inst is not None, "Failed to find " + inst_name
        assert original_inst.getPlacementStatus() == "NONE", inst_name + " is already placed"
        original_inst.setOrient(orient)
        original_inst.setLocation(x, y)
        original_inst.setPlacementStatus("FIRM")
        placed_cells_count += 1
    else:
        # must be a filler cell
        new_inst = odb.dbInst_create(block_top, db_top.findMaster(master_name), inst_name)
        assert new_inst is not None, "Failed to create " + inst_name
        new_inst.setOrient(orient)
        new_inst.setLocation(x, y)
        new_inst.setPlacementStatus("FIRM")
        created_cells_count += 1

# TODO: place the core macros within the padframe (chip floorplan)
for inst in block_top.getInsts():
    if inst.isPlaced() or inst.isFixed():
        continue
    print("Placing", inst.getName())
    master = inst.getMaster()
    master_width = master.getWidth()
    master_height = master.getHeight()
    print(master_width, master_height)
    print(width, height)

    inst.setLocation(width*1000//2-master_width//2, height*1000//2-master_height//2)
    inst.setPlacementStatus("PLACED")

odb.write_def(block_top, output_file_name)
print("Done")

