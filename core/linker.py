from contextlib import contextmanager

import compiler
import re

STUB_PRE = '__attribute__((noinline,weak)) '
STUB_POST = r' { __asm__ __volatile__ (".ascii \"patchkit-skip\""); }'
STUB_PRAGMA = r'''
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wreturn-type"
'''
STUB_PRAGMA_POP = r'''
#pragma GCC diagnostic pop
'''

func_re_1 = r'^(?P<all>(?P<desc>[^\s].+?(?P<name>{})(?P<args>\(.*?\)))\s*{(?P<body>(.|\n)+?)^})$'

class Decl:
    """
    symbol declaration class, describing a symbol declaration
    """

    def __init__(self, syms, source, headers):
        """inits a Decl class

        Args:
          syms (dict): {symbol_name : symbol_function_declartion(int C language form)}
          source (str): source of the symbol
          headers (str): C header of the symbol

        """
        self.syms = syms or {}
        self.source = source
        self._headers = headers
        self.cflags = None

    @property
    def headers(self):
        descs = '\n'.join([desc + ';' for desc in self.syms.values()])
        return '\n'.join([self._headers, descs])

    def inject(self, linker, sym):
        # TODO: alloc pos will shift between inject()
        # could use a separate segment for linker.
        addrs = {}
        with linker.binary.collect() as pt:
            # pt as in `def patch(pt)`
            if len(self.syms) > 1:
                pt.info('[LINK] {} (includes [{}])'.format(sym, ', '.join(self.syms.keys())))
            else:
                pt.info('[LINK] {}'.format(sym))
            # compile source
            asm = compiler.compile(self.source, linker, syms=self.syms.keys())

            table = '\n'.join([pt.arch.jmp('_' + sym) for sym in self.syms.keys()])
            sep = 'PATCHKITJMPTABLE'
            asm += ('\n.ascii "{}"\n__JMPTABLE__:\n'.format(sep)) + table
            addr = pt.binary.next_alloc('link')
            raw = pt.asm(asm, addr=addr, att_syntax=True)
            raw, jmps = raw.rsplit(sep, 1)
            for sym, ins in zip(self.syms.keys(), pt.arch.dis(jmps, addr=addr + len(sep) + len(raw))):
                addrs[sym] = ins.operands[0].imm

            # inject compiled source
            pt.inject(raw=raw, is_asm=True, target='link')
            return addrs

class Linker:
    def __init__(self, binary):
        self.binary = binary
        self.decls = []
        self.syms = {}
        self.addrs = {}

        self.pre_hooks = []
        self.post_hooks = []

    def __contains__(self, sym):
        return sym in self.syms

    def onpre(self, cb):
        self.pre_hooks.append(cb)

    def onpost(self, cb):
        self.post_hooks.append(cb)

    # symbol declaration helpers
    def declare(self, symbols=None, source='', headers=''):
        """declares a symbol with source and header
        
        The declaration actually remembers the information within this
        linker object, as `syms`, a `syms` property contains a tuple like
        (desc, decl) where desc is the function prototype and decl is the 
        Decl object

        Args:
          symbols (dict): a diction describing symbols, in form {symbol_name : symbol_function_declaration}
          source (str): symbol function source
          headers (str): header of the symbol declaration

        Returns:
          None

        """
        decl = Decl(symbols, source, headers)
        self.decls.append(decl)
        if symbols:
            for sym, desc in symbols.items():
                if sym in self.syms:
                    print 'Warning: duplicate symbol (%s)' % sym
                self.syms[sym] = (desc, decl)

    @staticmethod
    def getfunc(src, name):
        """searchs a function declaration in C source file

        Args:
          src (str): C source
          name (str): function name

        Returns:
          dict: matched content in dictionary

        """
        match = re.search(func_re_1.format(re.escape(name)), src, re.MULTILINE)
        return match.groupdict()

    def declarefuncs(self, src, names):
        """declares functions with source and names

        Args:
          src (str): C source
          names (list): names to declare

        Returns:
          None

        """
        for name in names:
            func = self.getfunc(src, name)
            self.declare(symbols={name: func['desc']}, source=func['all'])

    def autodecl(self, src):
        """declares all functions within a single source

        Args:
          src (str): the C source to declar functions within

        Returns:
          None

        """
        syms = [m[2] for m in re.findall(func_re_1.format('\w+'), src, re.MULTILINE)]

        for name in syms:
            func = self.getfunc(src, name)
            self.declare(symbols={name: func['desc']}, source=func['all'])

    # link-time logic
    def inject(self, sym):
        # injects the symbols within linker, and reserves the
        # addresses within `addrs`
        self.addrs.update(self.syms[sym][1].inject(self, sym))

    def resolve(self, sym):
        """resolves a symbol

        Args:
          sym (str): symbol to resolve

        Returns:
          int: resolved address

        """
        # after injection, we have our addresses containing 
        # the symbols, now we are able to resolve our own
        # symbols
        if not sym in self.addrs:
            # when not found, try find one in syms
            if sym in self.syms:
                # found, then inject it
                self.inject(sym)
            else:
                raise NameError(sym)
        return self.addrs[sym]

    # TODO: need a pt context so I can print stuff
    # TODO: should debug the "after" code?
    def pre(self, code, syms=()):
        """pre-hook called before compilation

        This is where we can inject our own symbols etc.

        Args:
          code (str): compiling code
          syms (?): ? TODO

        Returns:
          str: new code which needs to be compiled 

        """
        for cb in self.pre_hooks:
            tmp = cb(code, syms)
            if tmp:
                code = tmp

        headers = '\n'.join([decl.headers for decl in self.decls])
        stubs = []
        for name, (desc, _) in self.syms.items():
            if name in syms:
                continue
            stubs.append(STUB_PRE + desc + STUB_POST)
        stubs = STUB_PRAGMA + '\n'.join(stubs) + STUB_PRAGMA_POP
        code = '\n'.join([headers, code, stubs])
        return code
        # TODO: when does "source" get compiled here?
        # I think it'll get injected in post if a symbol is used

    def post(self, asm, syms=()):
        """post-hook called after compilation

        This does some filter after compilation

        Args:
          asm (str): compiled assembling
          syms (?): ? TODO

        Returns:
          str: new asm filtered

        """
        for cb in self.post_hooks:
            tmp = cb(asm, syms)
            if tmp:
                asm = tmp

        # strip stubs
        stubs = set(self.syms.keys()) - set(syms)
        refs = set()
        out = []
        buf = []
        skip = False
        valid_skip = False
        end_heuristic = re.compile(r'^([^.]\w+:|\s*)$')
        for line in asm.split('\n'):
            line = line.strip()
            if line.startswith(('.globl', '.weak_definition', '.weak', '.type', '.size')):
                continue
            if skip and (end_heuristic.match(line) or line.startswith('.cfi_endproc')):
                if not valid_skip:
                    out += buf
                buf = []
                skip = False
            if line.startswith(('.cfi_startproc', '.cfi_endproc')):
                continue
            for stub in stubs:
                if line.startswith('_%s:' % stub):
                    refs.add(stub)
                    skip = True
                    break

            if skip and 'patchkit-skip' in line:
                valid_skip = True
            if not skip:
                out.append(line)
            else:
                buf.append(line)

        asm = '\n'.join(out)
        while '\n\n\n' in asm:
            asm = asm.replace('\n\n\n', '\n\n')
        # resolve referenced addresses
        for ref in refs:
            # TODO: clean asm first?
            find_ref = r'\b_%s\b' % (re.escape(ref))
            if re.search(find_ref, asm):
                asm = re.sub(find_ref, '0x%x' % self.resolve(ref), asm)

        return asm
