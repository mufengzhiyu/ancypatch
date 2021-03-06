#!/usr/bin/env python

import binascii
import difflib
import itertools
import sys

from ancypatch.core.binary import Binary
from ancypatch.core.func import Func
from ancypatch.util import cfg

def hexdump(s, addr):
    lines = []
    for i in xrange(0, len(s), 16):
        chunks = [s[i+j:i+j+4] for j in xrange(0, 16, 4)]
        chunks += (4 - len(chunks)) * [' ' * 8]
        data = ' '.join(binascii.hexlify(chunk) for chunk in chunks)
        lines.append('0x%x: %s' % (addr, data))
    return '\n'.join(lines)

def dishex(pt, data, addr):
    dis = pt.arch.dis(data, addr=addr)
    spill = sum([len(i.bytes) for i in dis])
    extra = data[spill:]

    good = pt.pdis(dis)
    bad = hexdump(extra, addr=addr + spill)
    return filter(None, good.strip().split('\n') + bad.strip().split('\n'))

def diff(pt, a, b, addr):
    da = dishex(pt, a, addr)
    db = dishex(pt, b, addr)
    for line in itertools.islice(difflib.unified_diff(da, db), 3, None):
        pt.debug(line.strip())

def main():
    backtrack = False
    if len(sys.argv) >= 2 and sys.argv[1] == '--backtrack':
        sys.argv.pop(1)
        backtrack = True

    if len(sys.argv) != 3:
        print 'Usage: %s [--backtrack] <orig> <new>' % sys.argv[0]
        sys.exit(1)

    bina, binb = sys.argv[1:3]
    a = Binary(bina)
    b = Binary(binb)
    a.verbose = True
    b.verbose = True

    with a.collect() as pt, b.collect() as ptb:
        if pt.entry != ptb.entry:
            pt.debug('[-======== New Entry Point ========-]')
            pt.debug('[ENTRY] Moved 0x%x -> 0x%x' % (pt.entry, ptb.entry))
            ptb.debug(dis=ptb.dis(ptb.entry))

        pt.debug('')
        pt.debug('[-======== Function Diff ========-]')
        for func in pt.funcs():
            funcb = Func(ptb, func.addr, func.size)
            if func.read() == funcb.read():
                continue
            diff(pt, func.read(), funcb.read(), func.addr)

        pt.debug('')
        pt.debug('[-======== Exploring Branches ========-]')
        known = list(pt.funcs())
        new_funcs, selfmod = cfg.explore(ptb, known, backtrack=backtrack)
        if new_funcs:
            tmp = []
            for f in new_funcs:
                try:
                    da = pt.elf.read(f.addr, f.size)
                except Exception:
                    tmp.append(f)
                    continue
                db = ptb.elf.read(f.addr, f.size)
                if da != db:
                    tmp.append(f)
            new_funcs = tmp

            pt.debug('[-======== New Functions ========-]')
            for f in new_funcs:
                pt.debug(' - 0x%x +%d' % (f.addr, f.size))
            pt.debug('')

            for f in new_funcs:
                if f.addr == ptb.entry:
                    pt.debug('[FUNC] @0x%x (ENTRY POINT)' % f.addr)
                else:
                    pt.debug('[FUNC] @0x%x' % f.addr)

                fmt = lambda addrs: ', '.join(['0x%x' % x for x in addrs])
                if len(f.stacks) == 1:
                    pt.debug('  [call stack]: ' + fmt(list(f.stacks)[0]))
                elif f.stacks:
                    pt.debug('  [call stacks]:')
                    for stack in f.stacks:
                        pt.debug('    | %s' % fmt(stack))

                if f.xrefs:
                    pt.debug('  [xrefs]: %s' % fmt(f.xrefs))

                pt.debug(dis=f.dis())

                for (addr, size), data in selfmod:
                    if addr in f:
                        pt.warn('SELF-MODIFYING CODE')
                        ref = ptb.elf.read(addr, size)
                        diff(pt, ref, data, addr)

                pt.debug('')
            
        if selfmod:
            pt.debug('[-======== Old Functions (self-modifying) ========-]')
            for f in pt.funcs():
                for (addr, size), data in selfmod:
                    if addr in f:
                        pt.warn('SELF-MODIFYING CODE')
                        ref = ptb.elf.read(addr, size)
                        diff(pt, ref, data, addr)

if __name__ == '__main__':
    main()
