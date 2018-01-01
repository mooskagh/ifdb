#!/bin/env python3

import click
import re
import collections

SNIP_RE = re.compile(rb'[EWIDF](\d\d)(\d\d) (\S+) \S+ ([^\s:]+:\d+)\]')


@click.command()
@click.argument('input', type=click.File('rb'))
@click.option('--out', type=click.File('wb'))
def aggregate(input, out):
    cur_snippet = b''
    snip_example = dict()
    snip_count = collections.Counter()
    cur_fileloc = b''

    for line in input:
        m = SNIP_RE.match(line)
        if m:
            if cur_snippet and cur_fileloc:
                snip_example.setdefault(cur_fileloc, []).append(cur_snippet)
                cur_snippet = b''
            (month, day, time, fileloc) = m.groups()
            snip_count.update([fileloc])
            cur_fileloc = fileloc
        cur_snippet += line
    if cur_snippet and cur_fileloc:
        snip_example.setdefault(cur_fileloc, []).append(cur_snippet)

    for val, count in snip_count.most_common():
        click.echo("%5d %s" % (count, val))
        if out:
            out.write(b'========================================[ G5HF ]===\n')
            out.write(b'== %s (%d entries)\n' % (val, count))
            out.write(b'===================================================\n')
            for x in snip_example[val]:
                out.write(x)
                out.write(b'\n')


if __name__ == '__main__':
    aggregate()