#!/bin/env python
#
# glbdiff: diff the json in .glb files.
#
# Usage: glbdiff old_file new_file
#        glbdiff --textconv file            [textconv mode]
#        glbdiff --git ...                  [git mode]
#
# Integrating with git:
#
#     1. Add the following line to your .gitattributes:
#
#         *.glb diff=glbdiff
#
#     2. Add either of the following options to your git config:
#
#         [diff "glbdiff"]
#             textconv path/to/glbdiff.py --textconv
#
#         [diff "glbdiff"]
#             command path/to/glbdiff.py --git
#
# Using the 'textconv' option is recommended; it will allow git's own
# diff algorithms, colouring etc. to operate as usual; When using the
# 'command' option, git will just display the output from glbdiff.py
# verbatim.
#
# ----
#
# Copyright (c) 2023 vfig
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
import difflib, hashlib, json, optparse, os, struct, sys

def main(args):
    usage = ("usage: %prog [options] old_file new_file\n"
             "       %prog --textconv file")
    parser = optparse.OptionParser(usage)
    parser.add_option("--git",
        dest="mode", action="store_const", const="git",
        help="Git mode (for use as a git-diff command)")
    parser.add_option("--textconv",
        dest="mode", action="store_const", const="textconv",
        help="Convert a single file to text (for git-diff textconv)")
    options, args = parser.parse_args()
    if options.mode=='textconv':
        run_textconv(options, args)
    elif options.mode=='git':
        run_gitmode_diff(options, args)
    else:
        run_diff(options, args)

def fatal_error(message):
    prog = os.path.basename(sys.argv[0])
    sys.stderr.write(f"{prog}: {message}\n")
    sys.exit(1)

def write_tty(s):
    sys.stdout.write(s)

def write_pipe(s):
    sys.stdout.buffer.write(s.encode('utf-8'))

def run_diff(options, args):
    if len(args)!=2:
        args_str = " ".join(args)
        fatal_error(f"incorrect arguments: '{args_str}'. Try --help")
    old_file, new_file = args
    try:
        old_glb = GLB.from_file(old_file)
        new_glb = GLB.from_file(new_file)
        any_diffs = glb_diff(old_glb, new_glb)
    except Exception as e:
        fatal_error(str(e))

def run_gitmode_diff(options, args):
    # When used as a git diff command, the positional args will be:
    #
    #     path old-file old-hex old-mode new-file new-hex new-mode
    #
    if len(args)!=7:
        args_str = " ".join(args)
        fatal_error(f"incorrect arguments: '{args_str}'. Try --help")
    options.mode = None
    args = [args[1], args[4]]
    run_diff(options, args)

def run_textconv(options, args):
    if len(args)!=1:
        args_str = " ".join(args)
        fatal_error(f"incorrect arguments: '{args_str}'. Try --help")
    filename = args[0]
    try:
        glb = GLB.from_file(filename)
        any_diffs = glb_textconv(glb)
    except Exception as e:
        fatal_error(str(e))

def glb_diff(glb0, glb1):
    any_diffs = False
    if glb0.json_chunk != glb1.json_chunk:
        any_diffs = True
        lines0 = glb0.json_pretty.splitlines(True)
        lines1 = glb1.json_pretty.splitlines(True)
        difflines = difflib.unified_diff(lines0, lines1, glb0.filename, glb1.filename)
        writelines(difflines)
    if glb0.bin_chunk != glb1.bin_chunk:
        any_diffs = True
        write("Binary chunks differ.")
    if glb0.other_chunks != glb1.other_chunks:
        any_diffs = True
        write("Extra chunks differ.")
    return any_diffs

def glb_textconv(glb):
    alg = 'sha256'
    hash_func = getattr(hashlib, alg)
    write(glb.json_pretty)
    write('\n')
    if glb.bin_chunk:
        digest = hash_func(glb.bin_chunk).hexdigest()
        write(f"Binary chunk: {alg} {digest}\n")
    for chunk_type, chunk_data in glb.other_chunks:
        hex_type = "0x%08X"%chunk_type
        digest = hash_func(glb.bin_chunk).hexdigest()
        write(f"Extra chunk {hex_type}: {alg} {digest}\n")

class GLB:
    @classmethod
    def from_file(cls, filename):
        with open(filename, 'rb') as f:
            buffer = f.read()
        return cls(buffer, filename)

    def __init__(self, buffer, filename=''):
        self.filename = filename
        self._parse(buffer)

    def _parse(self, buffer):
        from struct import calcsize, unpack_from
        offset = 0
        file_header_format = '<III'
        magic, version, file_length = unpack_from(file_header_format, buffer, offset)
        offset += calcsize(file_header_format)
        if magic!=0x46546C67:
            raise ValueError("Not a GLB file (or invalid magic).")
        if version!=2:
            raise ValueError("Only GLB version 2 supported.")
        self.json_chunk = None
        self.bin_chunk = None
        self.other_chunks = []
        while offset<file_length:
            chunk_header_format = '<II'
            chunk_length, chunk_type = unpack_from(chunk_header_format, buffer, offset)
            offset += calcsize(chunk_header_format)
            chunk_data = buffer[offset:offset+chunk_length]
            offset += chunk_length
            if chunk_type==0x4E4F534A:
                self.json_chunk = chunk_data
            elif chunk_type==0x004E4942:
                self.bin_chunk = chunk_data
            else:
                self.other_chunks.append((chunk_type, chunk_data))
        self.json_parsed = json.loads(self.json_chunk)
        self.json_pretty = json.dumps(self.json_parsed, indent=4)
        self.json_pretty = self.json_pretty

if __name__=='__main__':
    write = write_tty if sys.stdout.isatty() else write_pipe
    main(sys.argv)
