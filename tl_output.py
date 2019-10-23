# Copyright (c) 2012-2015, Intel Corporation
# Author: Andi Kleen
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#
# This program is distributed in the hope it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# Output toplev results in various formats

import locale
import csv
import re
from tl_stat import isnan
from tl_uval import UVal, combine_uval


class Output:
    """Abstract base class for Output classes."""
    def __init__(self, logfile, version):
        self.logf = logfile
        self.printed_descs = set()
        self.hdrlen = 30
        self.version = version
        self.unitlen = 12
        self.belowlen = 0

    # pass all possible hdrs in advance to compute suitable padding
    def set_hdr(self, hdr, area):
        if area:
            hdr = "%-14s %s" % (area, hdr)
        self.hdrlen = max(len(hdr) + 1, self.hdrlen)

    def set_below(self, below):
        if below:
            self.belowlen = 1

    def set_unit(self, unit):
        self.unitlen = max(len(unit), self.unitlen)

    def set_cpus(self, cpus):
        pass

    def item(self, area, name, uval, timestamp, unit, desc, title, sample, bn, below):
        assert isinstance(uval, UVal)
        # --
        if desc in self.printed_descs:
            desc = ""
        else:
            self.printed_descs.add(desc)
        if not area:
            area = ""
        self.show(timestamp, title, area, name, uval, unit, desc, sample, bn, below)

    def ratio(self, area, name, uval, timestamp, unit, desc, title, sample, bn, below):
        uval.is_ratio = True
        self.item(area, name, uval, timestamp, unit, desc, title, sample, bn, below)

    def metric(self, area, name, uval, timestamp, desc, title, unit):
        uval.is_metric = True
        self.item(area, name, uval, timestamp, unit, desc, title, None, "", "")

    def flush(self):
        pass

class OutputHuman(Output):
    """Generate human readable single-column output."""
    def __init__(self, logfile, args, version, cpu):
        Output.__init__(self, logfile, version)
        try:
            locale.setlocale(locale.LC_ALL, '')
        except locale.Error:
            pass
        self.args = args
        self.titlelen = 7
        self.logf.write("# " + version + " on " + cpu.name + "\n")

    def set_cpus(self, cpus):
        if len(cpus) > 0:
            self.titlelen = max(map(len, cpus)) + 1

    def print_desc(self, desc, sample):
        if self.args.no_desc:
            return
        if desc:
            print >>self.logf, "\t" + desc
            if sample:
                print >>self.logf, "\t" + "Sampling events: ", sample

    def print_timestamp(self, timestamp):
        if timestamp:
            if isnan(timestamp):
                self.logf.write("%-11s " % "SUMMARY")
            else:
                self.logf.write("%6.9f " % timestamp)

    def print_header(self, area, hdr):
        if area:
            hdr = "%-14s %s" % (area, hdr)
        self.logf.write("%-*s " % (self.hdrlen, hdr))

    # timestamp Timestamp in interval mode
    # title     CPU
    # area      FE/BE ...
    # hdr       Node Name
    # val       Formatted measured value
    # unit      unit
    # desc      Object description
    # sample    Sample Objects (string)
    # vs        Statistics object
    # bn        marker for bottleneck
    # below     below if below, or ""
    # Example:
    # C0    BE      Backend_Bound:                                62.00 %
    def show(self, timestamp, title, area, hdr, val, unit, desc, sample, bn, below):
        self.print_timestamp(timestamp)
        write = self.logf.write
        if title:
            write("%-*s" % (self.titlelen, title))
        self.print_header(area, hdr)
        vals = "{:<{unitlen}} {:>} {:<{belowlen}}".format(
                    ("  " if unit[0] != "%" else "") + unit,
                    val.format_value(),
                    "?" if below else "",
                    unitlen=self.unitlen + 1,
                    belowlen=self.belowlen)
        if val.stddev:
            vals += " +- {:>8}".format(val.format_uncertainty())
        if bn:
            vals += " " + bn
        write(vals + "\n")
        self.print_desc(desc, sample)

    def metric(self, area, name, l, timestamp, desc, title, unit):
        l.is_metric = True
        self.item(area, name, l, timestamp, unit, desc, title, None, "", "")

def convert_ts(ts):
    if isnan(ts):
        return "SUMMARY"
    return ts

class OutputColumns(OutputHuman):
    """Human-readable output data in per-cpu columns."""
    def __init__(self, logfile, args, version, cpu):
        OutputHuman.__init__(self, logfile, args, version, cpu)
        self.nodes = dict()
        self.timestamp = None
        self.cpunames = set()
        self.printed_header = False

    def set_cpus(self, cpus):
        self.cpunames = cpus

    def show(self, timestamp, title, area, hdr, val, unit, desc, sample, bn, below):
        if self.args.single_thread:
            OutputHuman.show(self, timestamp, title, area, hdr, val, unit, desc, sample, bn, below)
            return
        self.timestamp = timestamp
        key = (area, hdr)
        if key not in self.nodes:
            self.nodes[key] = dict()
        assert title not in self.nodes[key]
        self.nodes[key][title] = (val, unit, desc, sample, bn, below)

    def flush(self):
        VALCOL_LEN = 16
        write = self.logf.write

        cpunames = sorted(self.cpunames)

        if not self.printed_header:
            if self.timestamp:
                write("%9s" % "")
            self.print_header("", "")
            for j in cpunames:
                write("%*s  " % (VALCOL_LEN, j))
            write("\n")
            self.printed_header = True

        for key in sorted(sorted(self.nodes.keys(), key=lambda x: x[1]), key=lambda x: x[0] == ""):
            node = self.nodes[key]
            desc = None
            sample = None
            unit = None
            if self.timestamp:
                self.print_timestamp(self.timestamp)

            self.print_header(key[0], key[1])
            vlist = []
            for cpuname in cpunames:
                if cpuname in node:
                    cpu = node[cpuname]
                    uval, unit, desc, sample, bn, below = cpu
                    v = uval.format_value()
                    vlist.append(uval)
                    write("%*s%s " % (VALCOL_LEN, v, "?" if below == "below" else "*" if bn else " "))
                else:
                    write("%*s  " % (VALCOL_LEN, ""))
            if unit:
                # XXX should move this to be per entry?
                cval = combine_uval(vlist)
                vs = (" +- " + cval.format_uncertainty() + " " + cval.format_mux()) if cval.stddev else ""
                write(" %-*s%s" % (self.unitlen, ("  " if unit[0] != "%" else "") + unit, vs))
            write("\n")
            self.print_desc(desc, sample)
        self.nodes = dict()

class OutputColumnsCSV(OutputColumns):
    """Columns output in CSV mode."""

    def __init__(self, logfile, sep, args, version, cpu):
        OutputColumns.__init__(self, logfile, args, version, cpu)
        self.writer = csv.writer(self.logf, delimiter=sep)
        self.printed_header = False
        self.writer.writerow(["# " + version + " on " + cpu.name])

    # XXX implement bn
    def show(self, timestamp, title, area, hdr, val, unit, desc, sample, bn, below):
        self.timestamp = timestamp
        key = (area, hdr)
        if key not in self.nodes:
            self.nodes[key] = dict()
        assert title not in self.nodes[key]
        self.nodes[key][title] = (val, unit + " " + below, desc, sample)

    def flush(self):
        cpunames = sorted(self.cpunames)
        if not self.printed_header:
            ts = ["Timestamp"] if self.timestamp else []
            self.writer.writerow(ts + ["Area", "Node"] + cpunames + ["Description", "Sample", "Stddev", "Multiplex"])
            self.printed_header = True
        for key in sorted(sorted(self.nodes.keys(), key=lambda x: x[1]), key=lambda x: x[0] == ""):
            node = self.nodes[key]
            ts = [convert_ts(self.timestamp)] if self.timestamp else []
            l = ts + [key[0], key[1]]
            vlist = []
            ol = dict()
            desc, sample = "", ""
            for cpuname in cpunames:
                if cpuname in node:
                    cpu = node[cpuname]
                    if cpu[2]:
                        desc = cpu[2]
                        desc = re.sub(r"\s+", " ", desc)
                    if cpu[3]:
                        sample = cpu[3]
                    # ignore unit for now
                    vlist.append(cpu[0])
                    ol[cpuname] = float(cpu[0].value) if cpu[0].value else ""
            l += [ol[x] if x in ol else "" for x in cpunames]
            l.append(desc)
            l.append(sample)
            vs = combine_uval(vlist)
            if vs:
                l += (vs.format_uncertainty().strip(), vs.format_mux().strip())
            else:
                l += ["", ""]
            self.writer.writerow(l)
        self.nodes = dict()

class OutputCSV(Output):
    """Output data in CSV format."""
    def __init__(self, logfile, sep, args, version, cpu):
        Output.__init__(self, logfile, version)
        self.writer = csv.writer(self.logf, delimiter=sep)
        self.args = args
        self.writer.writerow(["# " + version + " on " + cpu.name])

    def show(self, timestamp, title, area, hdr, val, unit, desc, sample, bn, below):
        if self.args.no_desc:
            desc = ""
        desc = re.sub(r"\s+", " ", desc)
        l = []
        if timestamp:
            l.append(convert_ts(timestamp))
        if title:
            l.append(title)
        stddev = val.format_uncertainty().strip()
        multiplex = val.multiplex if not isnan(val.multiplex) else ""
        self.writer.writerow(l + [hdr, val.format_value_raw().strip(),
                                  (unit + " " + ("?" if below else "")).strip(),
                                  desc, sample, stddev, multiplex, bn])
