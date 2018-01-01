#!/bin/env python3

import click
import re
import collections
import datetime

SNIP_RE = re.compile(rb'[EWIDF](\d\d\d\d) (\S+) \S+ ([^\s:]+:\d+)\]')


@click.command()
@click.argument('input', type=click.File('rb'))
@click.option('--out', type=click.File('wb'))
@click.option('--days', type=int)
def aggregate(input, out, days):
    allowed_days = set()
    if days is not None:
        today = datetime.date.today()
        for i in range(days + 1):
            ad = (
                today - datetime.timedelta(i)).strftime('%m%d').encode('utf-8')
            allowed_days.add(ad)

    cur_snippet = b''
    snip_example = dict()
    snip_count = collections.Counter()
    cur_fileloc = b''

    for line in input:
        m = SNIP_RE.match(line)
        if m:
            if cur_snippet and cur_fileloc:
                snip_example.setdefault(cur_fileloc, []).append(cur_snippet)
                snip_count.update([cur_fileloc])
            (day, time, fileloc) = m.groups()
            cur_snippet = b''
            cur_fileloc = fileloc
            if allowed_days and (day not in allowed_days):
                cur_fileloc = b''
        cur_snippet += line
    if cur_snippet and cur_fileloc:
        snip_example.setdefault(cur_fileloc, []).append(cur_snippet)
        snip_count.update([cur_fileloc])

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