#!/usr/bin/env python
# Copyright (c) 2026 The FLorey Institute of Neuroscience and Mental Health.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Covered Software is provided under this License on an "as is"
# basis, without warranty of any kind, either expressed, implied, or
# statutory, including, without limitation, warranties that the
# Covered Software is free of defects, merchantable, fit for a
# particular purpose or non-infringing.
# See the Mozilla Public License v. 2.0 for more details.

import math
import pathlib
from mrtrix3 import MRtrixError #pylint: disable=no-name-in-module
from mrtrix3 import app #pylint: disable=no-name-in-module
from mrtrix3 import matrix #pylint: disable=no-name-in-module
from mrtrix3 import run #pylint: disable=no-name-in-module



def usage(cmdline): #pylint: disable=unused-variable
  cmdline.set_author('Robert E. Smith (robert.smith@florey.edu.au)')
  cmdline.set_synopsis('Generate diffusion gradient tables in the DVS format for Siemens scanners')
  cmdline.add_description('Optimisations performed by the command:')
  cmdline.add_description('dirgen: Generate a set of directions of the requested number of volumes for each b-value'
                          ' in such a way that coverage of the half-sphere (accounting for antipodal symmetry) is maximally homogeneous.')
  cmdline.add_description('dirrotate: Rotate that set of directions on the sphere.'
                          ' For the largest b-value shell, this is optimised to minimise peak gradient load along any of the three physical axes.'
                          ' For all otehr shells, a random rotation is applied only to mitigate collinearity in directions across shells.')
  cmdline.add_description('dirsplit: If breaking the scheme into multiple subsets,'
                          ' this splits the directions of each b-value into that number of subsets'
                          ' in such a way that each individually achieves reasonably homogeneous coverage of the sphere'
                          ' (accounting for antipodal symmetry).')
  cmdline.add_description('dirflip: For each subset of each b-value shell,'
                          ' find a suitable set of those directions to flip antipodally'
                          ' such that the mean eddy current effects across the shell are close to zero.')
  cmdline.add_description('dirmerge: Arranges volumes across shells homoegeneously in time.')
  cmdline.add_description('b=0 volumes are inserted into the scheme manually using a tailored heuristic.'
                          ' Some number of b=0\'s will appear at the head of the table'
                          ' as these are typically to be used for susceptibility field estimation'
                          ' (b=0 volumes interspersed with DWI volumes can be affected by residual eddy currents):'
                          ' half of the b=0 volumes for smaller schemes, 4 volumes for larger schemes.'
                          ' The remaining b=0 volumes are distributed equally in time'
                          ' in such a way that the final volume acquired is always a b=0 volume,'
                          ' in case signal drift estimation is to be performed based on these volumes.')
  cmdline.add_argument('sets',
                       type=app.Parser.Int(1),
                       help='The number of sets into which to break the scheme')
  cmdline.add_argument('bzeros',
                       type=app.Parser.Int(2),
                       help='Total number of b=0 images')
  cmdline.add_argument('shells',
                       nargs='+',
                       type=app.Parser.Int(1),
                       metavar='<bvalue volumes>',
                       help='Additional b-value shells, provided as bvalue-volumecount pairs')
  cmdline.add_argument('output',
                       type=app.Parser.FileOut(),
                       help='The output DVS file')
  cmdline.add_argument('-export_grad_mrtrix',
                       type=app.Parser.FileOut(),
                       help='Export the gradient table in MRtrix3 format')




def execute(): #pylint: disable=unused-variable
  if app.ARGS.sets < 1:
    raise MRtrixError('Number of sets must be at least 1')
  if len(app.ARGS.shells) % 2:
    raise MRtrixError('Must provide shell information as bvalue - volumecount pairs')
  if app.ARGS.bzeros / app.ARGS.sets < 2:
    raise MRtrixError('Require at least two b=0 volumes per set')

  app.activate_scratch_dir()

  class Shell(object):
    def __init__(self, sets, bvalue, volumes):
      self.bvalue = bvalue
      self.volumes = volumes
      self.dirgen_path = pathlib.Path(f'dirs_{bvalue}.txt')
      self.dirrotate_path = pathlib.Path(f'{self.dirgen_path.with_suffix("")}_rotate.txt')
      self.dirsplit_paths = [ pathlib.Path(f'{self.dirrotate_path.with_suffix("")}_split{index}.txt')
                              for index in range(0, sets) ] \
                            if sets > 1 \
                            else [ self.dirrotate_path ]
      self.dirflip_paths = [ pathlib.Path(f'{filepath.with_suffix("")}_flip.txt')
                             for filepath in self.dirsplit_paths ]
      # dirorder is not used as dirmerge will itself change order of volumes
      #self.dirorder_paths = [ pathlib.Path(f'{filepath.with_suffix("")}_order.txt')
      #                        for filepath in self.dirflip_paths ]

  shells = [ ]

  bmax = max(app.ARGS.shells[0::2])

  for bvalue, volumes in zip(app.ARGS.shells[0::2], app.ARGS.shells[1::2]):
    shell = Shell(app.ARGS.sets, int(bvalue), int(volumes))
    # Generate the directions
    run.command(f'dirgen {shell.volumes} {shell.dirgen_path} -niter 1M -restarts 1K -cartesian')
    # Apply a rotation to the dataset
    # If this is the maximal b-value, then we want to minimise peak gradient load;
    #   otherwise, we want to just apply a random rotation,
    #   as we have no mechanism by which to perform any other kind of optimisation
    run.command(f'dirrotate {shell.dirgen_path} {shell.dirrotate_path}'
                f'{"" if bvalue == bmax else " -number 1"}'
                ' -cartesian')
    # Split the directions into discrete subsets
    if app.ARGS.sets > 1:
      run.command(f'dirsplit {shell.dirrotate_path} {" ".join(map(str, shell.dirsplit_paths))} -cartesian')
    for splitfile, flipfile in zip(shell.dirsplit_paths, shell.dirflip_paths):
      # Flip the directions to balance eddy currents
      run.command(f'dirflip {splitfile} {flipfile} -cartesian')
    shells.append(shell)

  # Manual combination of the different sets
  for set_index in range(0, app.ARGS.sets):

    # Make use of dirmerge instead of dirorder:
    #   this allows for some control of eddy current accumulation via unipolar model
    # Don't include b=0 volumes
    dirmerge_path = pathlib.Path(f'dirmerge_{set_index}.txt')
    run.command('dirmerge -unipolar 0.5 1 '
                + ' '.join(f'{item.bvalue} {item.dirflip_paths[set_index]}' for item in shells)
                + f' {dirmerge_path}')
    grad = [row[0:4] for row in matrix.load_matrix(dirmerge_path)]
    app.debug(f'Set {set_index}: {len(grad)} items in gradient table')

    # How many b=0 images in this set?
    bzero_count = round(app.ARGS.bzeros * (set_index+1) / float(app.ARGS.sets)) \
                  - round(app.ARGS.bzeros * set_index / float(app.ARGS.sets))
    app.debug(f'To insert {bzero_count} b=0 volumes into set {set_index}')

    # TESTME Rather than having a command-line option to affect this,
    #   just have a revised heuristic:
    # - If only 2 b=0's in the subset, have only 1 at the head
    # - If between 3 and 7 b=0's in the subset,
    #   have >= half the b=0's at the head
    # - If 8 or more b=0's in the subset,
    #   have four b=0's at the head
    bzero_count_head = ((bzero_count + 1) // 2) if bzero_count < 8 else 4
    app.debug(f'{bzero_count_head} of {bzero_count} b=0 volumes to appear at head of set {set_index}')
    new_grad = [[0, 0, 0, 0]] * bzero_count_head
    # TESTME This expression looked wrong to me?
    bzero_volume_increment = len(grad) / (bzero_count - bzero_count_head)
    app.debug(f'"bzero_volume_increment": {bzero_volume_increment}')
    bzero_accumulator = 0.0
    bzeros_to_insert = bzero_count - bzero_count_head
    for _ in range(0, bzeros_to_insert):
      bzero_accumulator += bzero_volume_increment
      volumes_from_grad = int(round(bzero_accumulator))
      new_grad.extend(grad[0:volumes_from_grad])
      grad = grad[volumes_from_grad:]
      new_grad.append([0, 0, 0, 0])
      bzero_accumulator -= volumes_from_grad
    grad = new_grad
    app.debug(f'Scheme set {set_index} has {len(grad)} elements after b=0 insertion')

    # Write the table having inserted the b=0 volumes to the scratch directory
    matrix.save_matrix(f'dirmerge_withbzero_{set_index}.b', grad)

    # We export the file at this level, since there's one file for each set
    if app.ARGS.export_grad_mrtrix:
      filename = app.ARGS.export_grad_mrtrix
      if app.ARGS.sets > 1:
        filename = pathlib.Path(f'{filename.with_suffix("")}_{set_index+1}'
                                f'{filename.suffix if filename.suffix else ".b"}')
      # TODO Custom export
      matrix.save_matrix(filename, grad)

    volume_index_digits = math.floor(math.log10(len(grad)-1))

    dvs = f'[directions={len(grad)-1}]\r\n'
    dvs += 'CoordinateSystem = xyz\r\n'
    dvs += 'Normalisation = none\r\n'
    # DVS file omits the first b=0 volume
    # (Typical sequence configuration involves selecting 2 b-values,
    #   b=0 and b=bmax,
    #   such that a single b=0 volume will be acquired
    #   prior to the contents of the table)
    for index, line_in in enumerate(grad[1:]):
      v = line_in[0:3]
      b = line_in[3]
      # Scale vector based on its ratio to the max b-value
      v = [value * math.sqrt(b) / math.sqrt(bmax) for value in v]
      dvs += f'Vector[{index}] ' \
             f'{" " * (volume_index_digits - math.floor(math.log10(max([1, index]))))} = ( ' \
             f'{", ".join("{:18.15f}".format(value) for value in v)}' \
             ' )\r\n'

    filename = pathlib.Path(app.ARGS.output)
    if app.ARGS.sets > 1:
      filename = filename.parent / f'{filename.name.split(".")[0]}_{set_index+1}.dvs'
    with open(filename, 'w') as f:
      f.write(dvs)
