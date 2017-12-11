#!/usr/bin/env python

import os
import sys

from ancypatch.core import Patcher
from optparse import OptionParser

def main():
    parser = OptionParser(usage='Usage: ancypatch [options] <binary> <patchdir> [patchdir...]')
    parser.add_option('-o', '--out', dest="out", help="output filename (default = <binary>.patched)")
    parser.add_option('-v', '--verbose', dest="verbose", action="store_true", help="verbose output")
    parser.add_option('-n', '--new', dest='new', help="create new binary from template/<new>")
    parser.add_option('--cflags', dest='cflags', help="add compiler flags to injected C")

    options, args = parser.parse_args()

    if len(args) < 2:
        parser.print_help()
        sys.exit(1)

    args = map(os.path.abspath, args)
    patchdirs = args[1:]

    if options.new:
        binary = os.path.join(os.path.dirname(__file__), 'template', options.new)
        defout = args[0]
    else:
        binary = args[0]
        defout = (binary + '.patched')

    out = os.path.abspath(options.out or defout)

    patch = Patcher(binary, verbose=options.verbose, cflags=options.cflags)
    for d in patchdirs:
        patch.add(d)

    patch.patch()
    patch.save(out)

if __name__ == '__main__':
    main()
