#!/usr/bin/env python
"""Turn on the LINTUL5 vernalisation response for the two winter crops.

Inherited state: no Brandenburg ``crop.xml`` defined ``VBASE``/``VERSAT``/
``VERNRT`` and no solution wired ``cVBASE``/``cVERSAT``/``cVERNRT`` into the
LINTUL5 ``Phenology`` component, so winter wheat and winter rapeseed developed on
pure thermal time. Vernalisation is the mechanism by which a warm winter DELAYS a
winter crop; without it warming could only accelerate phenology, so projected
anthesis under ssp370 was biased early and the yield effect of warming biased
optimistic. That was limitation #2 in CLAUDE.md; this script removes it.

What the component actually does (net.simplace.sim.components.models.lintul5
.Phenology, verified against the bytecode in simplace_5.0-3897.sif):

    double photoFactor = 1.0;
    if (IDSL == 1 && !FLOW) photoFactor = PHOTTB_interpol.getValueAt(DDLP);
    if (IDSL == 2 && !FLOW) photoFactor = PHOTTB_interpol.getValueAt(DDLP);
    double vernFactor = 1.0;
    if (IDSL == 2) {
        RVERNR = INSW(DVS - cVernalisationDevStage,
                      VERNRT_interpol.getValueAt(Tavg), 0.0);
        double vf = 1.0;
        if (VERSAT - VBASE != 0.0)
            vf = LIMIT(cMinimalVernalisationFactor, 1.0,
                       (VERN - VBASE) / (VERSAT - VBASE));
        vernFactor = INSW(DVS - cVernalisationDevStage, vf, 1.0);
    }
    // both multiply the pre-anthesis development rate

Three consequences that decide how this script is written:

1. ``IDSL == 2`` is the ONLY gate. Wiring the three inputs without setting IDSL
   to 2 changes nothing at all, silently.
2. ``IDSL == 2`` is a package deal: it enables the photoperiod response as well.
   Winter wheat moves 0 -> 2 here, so its PhotoperiodTableFactor becomes live.
   Its table is [0,8,12,18]h -> [0,1,1,1], i.e. factor 1.0 for any day longer
   than 8 h, so at 52-53 deg N the effect is ~1.0 for all but a few midwinter
   days at DVS ~0.1. Small, but NOT zero — which is why this script does not also
   copy the reference project's much steeper [0,17]h -> [0,1] table. Changing
   two mechanisms at once would make the calibration residual unattributable.
   Winter rapeseed is already IDSL=2, so for it this is a pure addition.
3. ``VERSAT - VBASE == 0`` is guarded, but ``VERNRT_interpol.getValueAt`` is
   called BEFORE that guard and ``cVERNRT`` defaults to null. Winter rapeseed has
   shipped as IDSL=2 with no VERNRT since it was inherited, so it was relying on
   that null path; wiring VERNRT removes the exposure.

Values come from the Germany-wide reference project
(``/data01/FDS/halder/soil-amelioration-scenarios``), which calibrated the same
LINTUL5 setup with vernalisation on. Both sit inside the bounds
``optimization/calibration.yaml`` already declares for the pair.

Edits, all idempotent, per winter crop:

  crop.xml            IDSL -> 2; VERSAT, VBASE, VERNRT added after IDSL
  solution.sol.xml    cVBASE / cVERSAT / cVERNRT into the Phenology component
  solution.sol.xml    VernalisationFactor + sVERN into the daily output, so what
                      the crop actually experienced is auditable after the fact
                      (the same reason patch_solution_co2.py records CO2)

Usage:
    python orchestration/patch_crop_vernalisation.py --check
    python orchestration/patch_crop_vernalisation.py --crop all
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Reference-project values. VERNRT is identical for both crops there: the classic
# WOFOST VERNRTB, as interleaved (mean temperature, vernalising rate) pairs —
# full rate between 3 and 10 C, falling to zero at -4 C and at 17 C.
VERNRT_PAIRS = [(-10.0, 0.0), (-4.0, 0.0), (3.0, 1.0),
                (10.0, 1.0), (17.0, 0.0), (30.0, 0.0)]

# ``retsum`` is a COUPLED, one-time correction: (from, to) for TSUM1, applied only
# when TSUM1 still holds the inherited value. Winter rapeseed is sown ~20 August
# into >17 C weather, where VERNRT's rate is 0, so VERN sits below VBASE and the
# factor clamps to exactly 0 (cMinimalVernalisationFactor defaults to 0.0 and
# nothing wires it) — development is frozen for ~5 weeks every autumn. With the
# inherited TSUM1=1097 the season then runs out before DVS 2: no maturity, no
# harvest, and therefore NO YEARLY OUTPUT AT ALL, which leaves the phenology
# objective with zero matched pairs and stage 1 unable to start. Measured at site
# 49612: maxDVS 1.61/1.93 vernalising vs 2.008/2.015 not, and 2.016/2.018 once
# TSUM1 is 400 — the value the reference project calibrated with vernalisation on.
#
# This is a STARTING POINT, not a calibrated value; stage 1 refines it (400 makes
# anthesis somewhat early, 1097 makes maturity unreachable, so the answer is
# between them). The `from` guard is what makes re-running safe: once TSUM1 holds
# anything else — in particular a value `calibrate.py promote` wrote — this step
# is skipped rather than clobbering it.
WINTER_CROPS: dict[str, dict] = {
    "winter_wheat":    {"VBASE": 14.0, "VERSAT": 70.0},
    "winter_rapeseed": {"VBASE": 7.0,  "VERSAT": 24.0, "retsum": (1097.0, 400.0)},
}

IDSL_LINE = ('    <parameter id="IDSL" description="pre-anthesis development depends on '
             'temperature (=0), temperature + day length (=1), or temperature + day length '
             '+ vernalisation (=2)" unit="-">2</parameter>')

CROP_RES_ENTRIES = (
    '\t\t\t\t<res id="VERSAT" description="saturated vernalisation requirement" '
    'datatype="DOUBLE" unit="http://www.wurvoc.org/vocabularies/om-1.8/day"/>\n'
    '\t\t\t\t<res id="VBASE" description="base vernalisation requirement" '
    'datatype="DOUBLE" unit="http://www.wurvoc.org/vocabularies/om-1.8/day"/>\n'
    '\t\t\t\t<res id="VERNRT" description="vernalising day rate vs mean temperature" '
    'datatype="DOUBLEARRAY" unit="http://www.wurvoc.org/vocabularies/om-1.8/one"/>\n')

PHENOLOGY_INPUTS = ('\t\t\t<input id="cVBASE" source="crop.VBASE"/>\n'
                    '\t\t\t<input id="cVERSAT" source="crop.VERSAT"/>\n'
                    '\t\t\t<input id="cVERNRT" source="crop.VERNRT"/>\n')

DAILY_VERN_OUT = (
    '\t\t\t\t<out id="VernalisationFactor" rule="Phenology.VernalisationFactor" '
    'description="multiplier on the pre-anthesis development rate (1 = fully vernalised)" '
    'datatype="DOUBLE" unit="-" format="%.6f"/>\n'
    '\t\t\t\t<out id="VERN" rule="Phenology.sVERN" '
    'description="accumulated vernalising days" datatype="DOUBLE" unit="d" format="%.6f"/>\n')


def vernalisation_block(vbase: float, versat: float) -> str:
    pairs = "\n".join(f"      <value>{t}</value>  <value>{r}</value>"
                      for t, r in VERNRT_PAIRS)
    return (
        f'    <parameter id="VERSAT" description="saturated vernalisation requirement" '
        f'unit="http://www.wurvoc.org/vocabularies/om-1.8/day">{versat}</parameter>\n'
        f'    <parameter id="VBASE" description="base vernalisation requirement" '
        f'unit="http://www.wurvoc.org/vocabularies/om-1.8/day">{vbase}</parameter>\n'
        f'    <parameter id="VERNRT" description="vernalising day rate as interleaved '
        f'(mean temperature [C], rate [-]) pairs" '
        f'unit="http://www.wurvoc.org/vocabularies/om-1.8/one">\n{pairs}\n    </parameter>\n')


def crop_is_patched(text: str) -> bool:
    return ('id="VERSAT"' in text and 'id="VBASE"' in text and 'id="VERNRT"' in text
            and re.search(r'<parameter id="IDSL"[^>]*>\s*2\s*</parameter>', text) is not None)


def solution_is_patched(text: str) -> bool:
    return ('source="crop.VERSAT"' in text and 'source="crop.VERNRT"' in text
            and '<res id="VERSAT"' in text and '<res id="VERNRT"' in text)


def patch_crop(text: str, vbase: float, versat: float,
               retsum: tuple[float, float] | None = None) -> tuple[str, list[str]]:
    done: list[str] = []

    if retsum:
        was, now = retsum
        m = re.search(r'(<parameter id="TSUM1"[^>]*>)\s*([0-9.]+)\s*(</parameter>)', text)
        if m and float(m.group(2)) == was:
            text = text[:m.start()] + f"{m.group(1)}{now:g}{m.group(3)}" + text[m.end():]
            done.append(f"TSUM1 {was:g} -> {now:g} (vernalisation needs a reachable maturity)")

    m = re.search(r'^[ \t]*<parameter id="IDSL".*?</parameter>[ \t]*$', text, flags=re.M | re.S)
    if not m:
        raise RuntimeError("IDSL parameter not found — cannot place the vernalisation block")

    # The inherited description stops at "(=1)" and never mentions that 2 is what
    # switches vernalisation on, so normalise the whole line. For a crop already
    # at 2 (winter rapeseed) this is a description fix and nothing else.
    if m.group(0).strip() != IDSL_LINE.strip():
        was_two = re.match(r'.*>\s*2\s*</parameter>$', m.group(0), flags=re.S) is not None
        text = text[:m.start()] + IDSL_LINE + text[m.end():]
        done.append("IDSL description normalised" if was_two else "IDSL -> 2")
        m = re.search(r'^[ \t]*<parameter id="IDSL".*?</parameter>[ \t]*$',
                      text, flags=re.M | re.S)

    if 'id="VERSAT"' not in text:
        text = text[:m.end()] + "\n" + vernalisation_block(vbase, versat).rstrip("\n") \
               + text[m.end():]
        done.append(f"VERSAT={versat}, VBASE={vbase}, VERNRT ({len(VERNRT_PAIRS)} pairs)")

    return text, done


def patch_solution(text: str) -> tuple[str, list[str]]:
    done: list[str] = []

    # The `crop` resource declares every parameter it exposes, one <res> per
    # parameter — it does NOT auto-discover them from crop.xml. Without these the
    # component inputs below link to nothing and SIMPLACE dies at startup with
    # `NullPointerException ... FWSimComponent.performLinks`, which names neither
    # the parameter nor the component. Add them first.
    if '<res id="VERSAT"' not in text:
        m = re.search(r'^[ \t]*<res id="IDSL"[^\n]*\n', text, flags=re.M)
        if not m:
            raise RuntimeError("IDSL res entry not found — cannot place the crop resource entries")
        text = text[:m.end()] + CROP_RES_ENTRIES + text[m.end():]
        done.append("crop resource VERSAT / VBASE / VERNRT")

    if 'source="crop.VERSAT"' not in text:
        m = re.search(r'^([ \t]*)<input id="cTEFFMX" source="crop\.TEFFMX"\s*/>[ \t]*$',
                      text, flags=re.M)
        if not m:
            raise RuntimeError("cTEFFMX input not found — cannot place the vernalisation inputs")
        text = text[:m.end()] + "\n" + PHENOLOGY_INPUTS.rstrip("\n") + text[m.end():]
        done.append("cVBASE / cVERSAT / cVERNRT")

    if 'id="VernalisationFactor"' not in text:
        m = re.search(r'(<output id="Daily_crop_growth".*?<out id="DevStage"[^\n]*\n)',
                      text, flags=re.S)
        if m:
            text = text[:m.end()] + DAILY_VERN_OUT + text[m.end():]
            done.append("daily output VernalisationFactor + VERN")

    return text, done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crop", default="all",
                    help=f"crop, comma list, or 'all' (winter crops only: {list(WINTER_CROPS)})")
    ap.add_argument("--check", action="store_true", help="report state, write nothing")
    args = ap.parse_args()

    picked = (list(WINTER_CROPS) if args.crop == "all"
              else [c.strip() for c in args.crop.split(",")])
    bad = [c for c in picked if c not in WINTER_CROPS]
    if bad:
        ap.error(f"not a winter crop: {bad}; choose from {list(WINTER_CROPS)}")

    rc = 0
    for crop in picked:
        xml = REPO_ROOT / "simplace" / crop / "data" / "crop" / "crop.xml"
        sol = REPO_ROOT / "simplace" / crop / "solution" / "solution.sol.xml"
        missing = [p for p in (xml, sol) if not p.exists()]
        if missing:
            print(f"  [ missing ] {crop}: {missing}")
            rc = 1
            continue

        crop_text, sol_text = xml.read_text(), sol.read_text()

        if args.check:
            ok = crop_is_patched(crop_text) and solution_is_patched(sol_text)
            state = "vernalising" if ok else "PURE THERMAL TIME"
            print(f"  [{state:>17s}] {crop}"
                  f"   crop.xml={'yes' if crop_is_patched(crop_text) else 'no':3s}"
                  f"  solution={'yes' if solution_is_patched(sol_text) else 'no'}")
            rc = rc or (0 if ok else 1)
            continue

        v = WINTER_CROPS[crop]
        new_crop, done_crop = patch_crop(crop_text, v["VBASE"], v["VERSAT"],
                                         v.get("retsum"))
        new_sol, done_sol = patch_solution(sol_text)
        if not (done_crop or done_sol):
            print(f"  [ unchanged ] {crop} (already vernalising)")
            continue
        if done_crop:
            xml.write_text(new_crop)
        if done_sol:
            sol.write_text(new_sol)
        print(f"  [  patched  ] {crop}: {', '.join(done_crop + done_sol)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
