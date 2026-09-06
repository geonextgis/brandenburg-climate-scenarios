#!/usr/bin/env python
"""Wire scenario CO2 into a crop's SIMPLACE solution, in place of a constant.

The Brandenburg solutions inherited from the 1 km workspace drive LINTUL5's
radiation-use efficiency from a **fixed** atmospheric CO2 concentration:

    <var id="vCO2" datatype="DOUBLE">380</var>
    ...
    <simcomponent id="RadiationUseEfficiency" ...>
      <input id="cCO" source="vCO2"/>

380 ppm is roughly the year-2000 atmosphere. Left in place, an ssp370 run to
2100 would experience 2000-level CO2 for its whole length: the temperature and
precipitation of the scenario, with none of the fertilisation. Every yield
change would then be climate-only, and the CO2 term of the scenario would be
silently missing rather than deliberately excluded.

This script replaces the constant with a monthly record read from
``${_WORKDIR_}/data/co2/co2.csv``, which ``generate.py`` stages per experiment
from ``climate/co2/`` — observed for DWD/HYRAS-OBS/historical, the matching SSP
record for a future run.

Four edits, each idempotent:

1. ``<interface id="co2observedfile">``    after the ``locationfile`` interface
2. ``<resource id="co2observed">``          after the ``location`` resource,
   at DAILY frequency keyed on ``(CURRENT.YEAR, CURRENT.MONTH)``
3. ``<simcomponent id="CO2Supply">``        before ``RadiationUseEfficiency``,
   exposing the monthly value as a daily driving variable
4. ``cCO`` rebound from ``vCO2`` to ``CO2Supply.CO2``; ``vCO2`` is retained but
   commented, so the previous behaviour stays legible in the diff

It also adds ``CO2`` to the daily and yearly output headers, so what the crop
actually experienced is recorded next to the yield it produced — without that a
run cannot be audited after the fact.

How CO2 then reaches growth: ``RadiationUseEfficiency`` interpolates
``crop.COTableFactor`` against ``crop.COTableCo2`` (both already present in every
crop.xml) to scale RUE, and returns ``RTMCO``, the CO2 transpiration-ratio
modifier, which ``LintulWaterStress`` uses. So CO2 acts on assimilation and on
water use, which is the LINTUL5 fertilisation response.

Usage:
    python orchestration/patch_solution_co2.py --crop all
    python orchestration/patch_solution_co2.py --crop winter_wheat --check
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

CO2_INTERFACE = """\t\t<interface id="co2observedfile" type="CSV">
\t\t\t<poolsize>2</poolsize>
\t\t\t<divider>,</divider>
\t\t\t<filename>${_WORKDIR_}/data/co2/co2.csv</filename>
\t\t</interface>
"""

CO2_RESOURCE = """\t\t<resource id="co2observed" interface="co2observedfile" frequence="DAILY">
\t\t\t<header>
\t\t\t\t<res id="year" datatype="INT" key="CURRENT.YEAR"/>
\t\t\t\t<res id="month" datatype="INT" key="CURRENT.MONTH"/>
\t\t\t\t<res id="CO2" datatype="DOUBLE" description="monthly mean CO2 concentration (ppm) from data/co2/co2.csv, staged per climate scenario"/>
\t\t\t</header>
\t\t</resource>
"""

CO2_COMPONENT = """\t\t<simcomponent id="CO2Supply" class="net.simplace.sim.components.FWSimpleSimComponent">
\t\t\t<description title="Provide monthly CO2 as a daily driving variable">Uses co2observed.CO2 (data/co2/co2.csv, staged per climate scenario).</description>
\t\t\t<process>
\t\t\t\t<var id="CO2" datatype="DOUBLE" rule="${co2observed.CO2}"/>
\t\t\t</process>
\t\t</simcomponent>
\t\t<!-- #################################################################################################### -->
"""

DAILY_CO2_OUT = ('\t\t\t\t<out id="CO2" rule="CO2Supply.CO2" description="monthly CO2 '
                 'concentration (ppm) driving RadiationUseEfficiency" datatype="DOUBLE" '
                 'format="%.4f"/>\n')
YEARLY_CO2_OUT = ('\t\t\t\t<out id="CO2" datatype="DOUBLE" mode="AVG" description="monthly CO2 '
                  'concentration (ppm) driving RadiationUseEfficiency" rule="CO2Supply.CO2" '
                  'format="%.4f"/>\n')


def is_patched(text: str) -> bool:
    return 'id="CO2Supply"' in text and 'source="CO2Supply.CO2"' in text


def patch(text: str) -> tuple[str, list[str]]:
    """Return the patched solution and a log of what changed."""
    done: list[str] = []

    # 1. CO2 input interface, right after the locationfile interface.
    if 'id="co2observedfile"' not in text:
        m = re.search(r'\t\t<interface id="locationfile".*?</interface>\n',
                      text, flags=re.DOTALL)
        if not m:
            raise RuntimeError("locationfile interface not found — cannot place co2observedfile")
        text = text[:m.end()] + CO2_INTERFACE + text[m.end():]
        done.append("interface co2observedfile")

    # 2. CO2 resource, right after the location resource. DAILY frequency with a
    #    (year, month) key: the record is monthly, the lookup happens every
    #    simulated day, and a month with no row is a NullPointerException.
    if 'id="co2observed"' not in text:
        m = re.search(r'\t\t<resource id="location" .*?</resource>\n', text, flags=re.DOTALL)
        if not m:
            raise RuntimeError("location resource not found — cannot place co2observed")
        text = text[:m.end()] + CO2_RESOURCE + text[m.end():]
        done.append("resource co2observed")

    # 3. CO2Supply component, immediately before RadiationUseEfficiency.
    if 'id="CO2Supply"' not in text:
        anchor = '\t\t<simcomponent id="RadiationUseEfficiency"'
        if anchor not in text:
            raise RuntimeError("RadiationUseEfficiency component not found")
        text = text.replace(anchor, CO2_COMPONENT + anchor, 1)
        done.append("simcomponent CO2Supply")

    # 4. Rebind cCO. The constant is kept, commented, so the change is legible.
    if '<input id="cCO" source="vCO2"/>' in text:
        text = text.replace('<input id="cCO" source="vCO2"/>',
                            '<input id="cCO" source="CO2Supply.CO2"/>', 1)
        done.append("cCO -> CO2Supply.CO2")
    if re.search(r'^\s*<var id="vCO2" datatype="DOUBLE">380</var>\s*$', text, flags=re.M):
        text = re.sub(
            r'^(\s*)<var id="vCO2" datatype="DOUBLE">380</var>\s*$',
            r'\1<!-- vCO2 was the fixed 380 ppm forcing; CO2 now comes from '
            r'data/co2/co2.csv via CO2Supply (see orchestration/patch_solution_co2.py) -->\n'
            r'\1<!-- <var id="vCO2" datatype="DOUBLE">380</var> -->',
            text, count=1, flags=re.M)
        done.append("vCO2 constant commented out")

    # 5. Record what the crop actually experienced, beside the yield it produced.
    if 'id="CO2Supply"' in text:
        m = re.search(r'(<output id="Daily_crop_growth".*?<out id="DevStage"[^\n]*\n)',
                      text, flags=re.DOTALL)
        if m and DAILY_CO2_OUT.strip() not in text:
            text = text[:m.end()] + DAILY_CO2_OUT + text[m.end():]
            done.append("daily output CO2")
        m = re.search(r'(<output id="LintulYearly".*?<out id="DevStage"[^\n]*\n)',
                      text, flags=re.DOTALL)
        if m and YEARLY_CO2_OUT.strip() not in text:
            text = text[:m.end()] + YEARLY_CO2_OUT + text[m.end():]
            done.append("yearly output CO2")

    return text, done


def main() -> int:
    cfg = yaml.safe_load((REPO_ROOT / "orchestration" / "experiments.yaml").read_text())
    crops = list(cfg["crops"])

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crop", default="all", help="crop, comma list, or 'all'")
    ap.add_argument("--check", action="store_true", help="report state, write nothing")
    args = ap.parse_args()

    picked = crops if args.crop == "all" else [c.strip() for c in args.crop.split(",")]
    bad = [c for c in picked if c not in crops]
    if bad:
        ap.error(f"unknown crop(s): {bad}; choose from {crops}")

    rc = 0
    for crop in picked:
        sol = REPO_ROOT / "simplace" / crop / "solution" / "solution.sol.xml"
        if not sol.exists():
            print(f"  [ missing ] {crop}: {sol}")
            rc = 1
            continue
        text = sol.read_text()
        if args.check:
            state = "co2-driven" if is_patched(text) else "FIXED 380 ppm"
            print(f"  [{state:>13s}] {crop}")
            rc = rc or (0 if is_patched(text) else 1)
            continue
        new, done = patch(text)
        if not done:
            print(f"  [ unchanged ] {crop} (already CO2-driven)")
            continue
        sol.write_text(new)
        print(f"  [  patched  ] {crop}: {', '.join(done)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
