#!/usr/bin/env python

import binascii
import difflib
import itertools
import sys

from ancypatch.core.binary import Binary
from ancypatch.util import cfg

def main():
    backtrack = False
    if len(sys.argv) >= 2 and sys.argv[1] == '--backtrack':
        sys.argv.pop(1)
        backtrack = True

    if len(sys.argv) != 2:
        print 'Usage: %s [--backtrack] <binary>' % sys.argv[0]
        sys.exit(1)

    bina = sys.argv[1]
    a = Binary(bina)
    a.verbose = True

    with a.collect() as pt:
        pt.debug('[-======== Exploring Branches ========-]')
        known = list(pt.funcs())
        new_funcs, selfmod = cfg.explore(pt, known, backtrack=backtrack)
        pt.debug('[*] Functions')
        funcs = sorted(known + new_funcs, key=lambda x: x.addr)
        for func in funcs:
            pt.debug(' - 0x%x 0x%x' % (func.addr, func.addr + func.size))

        pt.debug('')
        for func in funcs:
            pt.debug('[FUNC] 0x%x-0x%x' % (func.addr, func.addr + func.size))
            pt.debug(dis=func.dis())
            pt.debug('')

        with pt.relopen('funcs', 'w') as f:
            for func in funcs:
                f.write('%08x %08x\n' % (func.addr, func.addr + func.size))

if __name__ == '__main__':
    main()
