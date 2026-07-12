"""
EBSD Texture Analysis for Fe-3%Si Non-Oriented Electrical Steel
=================================================================

Uses the `orix` package (https://orix.readthedocs.io) to:

  1. Convert grain-averaged Bunge Euler angles (phi1, Phi, phi2) into
     {hkl}<uvw> orientation notation for every indexed grain, reduced to
     a self-consistent, symmetry-canonical representation so the result
     can be used directly for ontology / rule-based inference (see
     "CANONICAL REPRESENTATION" note below).
  2. Quantify the area (volume) fraction and number fraction of grains
     belonging to the classic BCC rolling/recrystallization texture
     components:
         - Cube            {001}<100>
         - Goss            {110}<001>
         - Rotated Goss    {110}<1-10>
         - Rotated Cube    {001}<110>
     and the four texture fibers:
         - Lambda (theta) fiber : <100> // ND
         - Gamma fiber          : <111> // ND
         - Eta fiber            : <001> // RD
         - Alpha fiber          : <110> // RD

Crystal symmetry: cubic m-3m (Oh, Laue class of ferrite/BCC-Fe), the
correct equivalence group for indexing/orientation-equivalence of a
centrosymmetric cubic phase, used for all disorientation/misorientation
calculations (angle_with_outer below).

Convention (verified numerically against orix 0.14, matches classical
Bunge notation, Randle & Engler "Texture Analysis"):
    g = Orientation.to_matrix()
    row 0 of g  -> RD expressed in crystal coordinates -> gives [uvw]
    row 2 of g  -> ND expressed in crystal coordinates -> gives (hkl)

CANONICAL REPRESENTATION (this is the fix over the previous version)
----------------------------------------------------------------------
A raw grain orientation has 24 equally-valid {hkl}<uvw> descriptions
(cubic crystal symmetry, proper rotation subgroup "432", 24 elements),
e.g. (110)[001] and (011)[100] describe the *same* physical orientation
(Goss). Printing the description that falls straight out of the raw
Euler angles is therefore essentially arbitrary and will often NOT look
like the textbook/ideal notation, even for grains that ARE, physically,
very close to a named component.

To fix this, for every grain we search over all 24 proper-rotation
symmetry operations S of the cubic point group and pick the one that
brings the grain's ND vector closest to the standard IPF fundamental
sector (0 <= h <= k <= l convention, same triangle as the 001-101-111
color key in your Fig. 3). The SAME operation S is then applied to RD,
so the printed (hkl)[uvw] pair remains a single, self-consistent,
orthogonal Miller-index pair (not two independently-reduced vectors).

On top of that, grains that fall within TOL_COMPONENT of a *named*
ideal component (Cube, Goss, Rotated Goss, Rotated Cube) are printed
using that ideal component's exact, textbook {hkl}<uvw> plus the
residual disorientation angle, e.g. "~(001)[100] Cube, D=9.2 deg" -
this directly mirrors the classification in Output 2 and is what makes
the result usable for downstream ontology / rule-based inference.

"""

import os
import numpy as np
import pandas as pd
from fractions import Fraction
from orix.quaternion import Orientation, symmetry
from orix.vector import Vector3d

# ----------------------------------------------------------------------
# USER-ADJUSTABLE PARAMETERS
# ----------------------------------------------------------------------
DATA_FILE = "../EBSD.txt"
OUT_DIR = "../"

TOL_COMPONENT = 15.0   # deg, max disorientation to an ideal texture component
TOL_FIBER = 15.0       # deg, max deviation of the fiber axis from ND / RD
MAX_MILLER_INDEX = 9   # largest index allowed when rounding "Other" grains to {hkl}<uvw>

CRYSTAL_SYMMETRY = symmetry.Oh   # m-3m, correct Laue class for ferrite (BCC-Fe, cubic)
PROPER_ROTATION_GROUP = symmetry.O  # 24 proper rotations, used for axis relabeling

os.makedirs(OUT_DIR, exist_ok=True)

# ----------------------------------------------------------------------
# 1. READ THE GRAIN FILE
# ----------------------------------------------------------------------
# Columns (see file header):
#   0-2 : phi1, Phi, phi2  (deg)
#   3-5 : phi1, Phi, phi2  (rad)   [not used, degrees are more precise here]
#   6-7 : x, y (microns, grain centroid)
#   8   : grain area (micron^2)
#   9   : grain diameter (micron)
df = pd.read_csv(DATA_FILE, comment="#", header=None)
df.columns = ["phi1", "Phi", "phi2", "phi1_rad", "Phi_rad", "phi2_rad",
              "x", "y", "area", "diameter"]

euler_deg = df[["phi1", "Phi", "phi2"]].to_numpy()
n_grains = len(df)
print(f"Loaded {n_grains} grains from {DATA_FILE}")

# ----------------------------------------------------------------------
# 2. BUILD ORIX ORIENTATIONS
# ----------------------------------------------------------------------
ori = Orientation.from_euler(np.deg2rad(euler_deg), symmetry=CRYSTAL_SYMMETRY)

# Raw orientation matrices: g[:,0,:]=RD in crystal frame, g[:,2,:]=ND in crystal frame
g_raw = ori.to_matrix()
RD_raw = g_raw[:, 0, :]
ND_raw = g_raw[:, 2, :]


# ----------------------------------------------------------------------
# 3. IDEAL TEXTURE COMPONENTS -> orix Orientation objects
# ----------------------------------------------------------------------
def orientation_from_hkl_uvw(hkl, uvw, sym=CRYSTAL_SYMMETRY):
    """Build the orientation matrix for an ideal {hkl}<uvw> component.
    ND = hkl (normalized), RD = uvw (normalized), TD = ND x RD.
    Requires hkl . uvw = 0 (Miller notation validity check).

    Gmat is built with rows [RD; TD; ND] (matching the row convention
    documented at the top of this file for Orientation.to_matrix()
    output). But Orientation.from_matrix()'s symmetry-equivalence
    machinery (Misorientation.equivalent(): `Gr.outer(M)`, crystal
    symmetry as the *left* quaternion factor) expects the *transpose* of
    that convention as input to generate the textbook-correct family of
    equivalent {hkl}<uvw} representations -- passing Gmat un-transposed
    silently produces a different, non-standard 24-element orbit that
    does not match crystallographically valid equivalents (verified
    against the true symmetry orbit of Goss {110}<001>, e.g. it wrongly
    excludes (101)[010] and includes non-equivalent (0,0,1)-type
    entries). Feeding Gmat.T fixes this."""
    ND = np.array(hkl, dtype=float)
    RD = np.array(uvw, dtype=float)
    assert abs(np.dot(ND, RD)) < 1e-8, f"{hkl}<{uvw}> is not a valid {{hkl}}<uvw> (not orthogonal)"
    ND = ND / np.linalg.norm(ND)
    RD = RD / np.linalg.norm(RD)
    TD = np.cross(ND, RD)
    Gmat = np.array([RD, TD, ND])
    return Orientation.from_matrix(Gmat.T[None, :, :], symmetry=sym)


IDEAL_COMPONENTS = {
    "Cube {001}<100>":          {"hkl": (0, 0, 1), "uvw": (1, 0, 0)},
    "Goss {110}<001>":          {"hkl": (1, 1, 0), "uvw": (0, 0, 1)},
    "Rotated Goss {110}<1-10>": {"hkl": (1, 1, 0), "uvw": (1, -1, 0)},
    "Rotated Cube {001}<110>":  {"hkl": (0, 0, 1), "uvw": (1, 1, 0)},
}
IDEAL_ORIENTATIONS = {
    name: orientation_from_hkl_uvw(v["hkl"], v["uvw"])
    for name, v in IDEAL_COMPONENTS.items()
}

# Disorientation of every grain to every ideal component (crystal symmetry
# equivalents are automatically searched by orix because both `ori` and the
# ideal orientations carry symmetry=Oh).
angles_to_component = {}
for name, ideal in IDEAL_ORIENTATIONS.items():
    ang = ideal.angle_with_outer(ori, degrees=True)[0]  # shape (n_grains,)
    angles_to_component[name] = ang

comp_angle_df = pd.DataFrame(angles_to_component)
best_component = comp_angle_df.idxmin(axis=1)
best_angle = comp_angle_df.min(axis=1)
is_classified = best_angle <= TOL_COMPONENT
component_label = np.where(is_classified, best_component, "Other/Random")


# ----------------------------------------------------------------------
# 4. CANONICAL, SYMMETRY-CONSISTENT {hkl}<uvw> FOR EVERY GRAIN
# ----------------------------------------------------------------------
# Target: reduce each grain's ND vector into the standard cubic IPF
# fundamental sector (0<=h<=k<=l convention), then find the ONE proper
# cubic symmetry operation S (of the 24) that brings the raw ND vector
# closest to that target, and apply the SAME S to RD. This keeps
# (hkl)/[uvw] as one self-consistent, orthogonal Miller-index pair,
# just re-labeled using the crystallographically standard axis choice.
target_nd = Vector3d(ND_raw).in_fundamental_sector(CRYSTAL_SYMMETRY).data  # (N,3)

S_mats = PROPER_ROTATION_GROUP.to_matrix()  # (24, 3, 3)
cand_nd = np.einsum('gi,sij->sgj', ND_raw, S_mats)          # (24, N, 3)
cos_to_target = np.clip(np.abs(np.einsum('sgj,gj->sg', cand_nd, target_nd)), -1.0, 1.0)
ang_to_target = np.degrees(np.arccos(cos_to_target))         # (24, N)
best_op = np.argmin(ang_to_target, axis=0)                   # (N,)

S_best = S_mats[best_op]                                     # (N, 3, 3)
ND_canon = np.einsum('gi,gij->gj', ND_raw, S_best)
RD_canon = np.einsum('gi,gij->gj', RD_raw, S_best)


# ----------------------------------------------------------------------
# 5. CONVERT DIRECTION VECTORS TO SMALL-INTEGER MILLER INDICES
# ----------------------------------------------------------------------
def vector_to_miller(vec, max_denom=MAX_MILLER_INDEX):
    """
    Rational approximation of a unit direction vector as small integer
    Miller indices. Used only as a fallback for grains that do not fall
    within tolerance of a named ideal component (see section 6) -- for
    those, individual grains rarely sit exactly on a low-index
    orientation, so this returns the *nearest* simple {hkl}/[uvw]
    representation, which can still have somewhat large indices if the
    grain is genuinely far from any simple orientation.
    """
    v = np.asarray(vec, dtype=float)
    max_abs = np.max(np.abs(v))
    if max_abs < 1e-12:
        return (0, 0, 0)
    v = v / max_abs  # largest component -> +-1
    fracs = [Fraction(float(x)).limit_denominator(max_denom) for x in v]
    denom_lcm = np.lcm.reduce([f.denominator for f in fracs])
    ints = np.array([int(f * denom_lcm) for f in fracs], dtype=int)
    nz = ints[ints != 0]
    gcdv = np.gcd.reduce(np.abs(nz)) if len(nz) else 1
    gcdv = gcdv if gcdv != 0 else 1
    ints = ints // gcdv
    return tuple(int(i) for i in ints)


def fmt_plain(t, brackets):
    """Plain crystallographic string, no spaces, negatives written as
    a normal minus sign (e.g. (0,0,1)->'(001)', (-1,1,1)->'[-111]').
    NOTE: this concatenated format is only unambiguous for single-digit
    indices (which is always the case for the four named ideal
    components below). Fallback indices for 'Other/Random' grains can
    occasionally have two-digit values, in which case the concatenated
    string is genuinely ambiguous to a human/ontology reader -- this is
    a limitation of the requested no-space format, not of the underlying
    numbers (the exact integers are also kept, comma-separated, in the
    *_int helper columns for anyone who needs to parse them back out)."""
    o, c = brackets
    return f"{o}{''.join(str(v) for v in t)}{c}"


canon_hkl_list = [vector_to_miller(v) for v in ND_canon]
canon_uvw_list = [vector_to_miller(v) for v in RD_canon]

# ----------------------------------------------------------------------
# 6. FIBER CLASSIFICATION (moved ahead of Section 7 -- its result now
#    also feeds into building the final hkl/uvw columns, not just the
#    separate per-grain classification table in Section 9)
# ----------------------------------------------------------------------
FAMILY_AXES_INT = {
    "100": [(1, 0, 0), (0, 1, 0), (0, 0, 1)],
    "110": [(1, 1, 0), (1, -1, 0), (1, 0, 1), (1, 0, -1), (0, 1, 1), (0, 1, -1)],
    "111": [(1, 1, 1), (1, 1, -1), (1, -1, 1), (-1, 1, 1)],
}


def family_directions(family):
    """Unique crystallographic <uvw>-type axes (line directions, sign-free)
    for the requested cubic family, as unit vectors."""
    v = np.array(FAMILY_AXES_INT[family], dtype=float)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def min_angle_to_family(vectors, family_dirs):
    """vectors: (N,3) unit vectors. family_dirs: (M,3) unit vectors.
    Returns (N,) minimum angle (deg) between each vector and its closest
    family axis (direction sense ignored, i.e. using |dot|)."""
    cos = np.abs(vectors @ family_dirs.T)  # (N, M)
    cos = np.clip(cos, -1.0, 1.0)
    ang = np.degrees(np.arccos(cos))
    return ang.min(axis=1)


def snap_to_family(vec, family):
    """Returns the small-integer (h,k,l) of whichever axis in `family` is
    closest to `vec`, signed to match vec's actual direction sense (not
    just the sign-free line) -- e.g. snap_to_family(v, "100") picks
    whichever of +-[100]/+-[010]/+-[001] is nearest v and returns it with
    the correct sign. Used to "clean" a grain's hkl/uvw onto an exact
    fiber-representative index, the same way an is_classified grain
    already gets snapped onto an exact point-component index below."""
    axes_int = np.array(FAMILY_AXES_INT[family], dtype=float)
    axes_unit = axes_int / np.linalg.norm(axes_int, axis=1, keepdims=True)
    dots = axes_unit @ np.asarray(vec, dtype=float)
    idx = int(np.argmax(np.abs(dots)))
    sign = 1 if dots[idx] >= 0 else -1
    return tuple(int(sign * x) for x in axes_int[idx])


FIBERS = {
    "Lambda fiber <100>//ND": (ND_raw, "100"),
    "Gamma fiber <111>//ND":  (ND_raw, "111"),
    "Eta fiber <001>//RD":    (RD_raw, "100"),  # <001> is a member of <100>
    "Alpha fiber <110>//RD":  (RD_raw, "110"),
}

fiber_membership = {}
fiber_deviation = {}
for name, (sample_dir, family) in FIBERS.items():
    dev = min_angle_to_family(sample_dir, family_directions(family))
    fiber_deviation[name] = dev
    fiber_membership[name] = dev <= TOL_FIBER

fiber_dev_df = pd.DataFrame(fiber_deviation)
fiber_mem_df = pd.DataFrame(fiber_membership)

# ----------------------------------------------------------------------
# 7. BUILD FINAL hkl / uvw COLUMNS (clean, ontology-ready)
# ----------------------------------------------------------------------
# For grains classified within tolerance of a named component, hkl/uvw
# are that component's exact ideal indices -- already exactly on-axis for
# their fiber too (e.g. Cube's ND=[001] is already exactly <100>), so no
# further snapping needed.
#
# For "Other/Random" grains, hkl and uvw are handled independently: if
# ND is within TOL_FIBER of the Lambda or Gamma fiber axis, hkl is
# snapped to that exact fiber-representative index (Lambda checked
# first; the <100>/<111> axis sets are >30 deg apart everywhere, so a
# grain can never legitimately qualify for both). Same for uvw against
# Eta/Alpha via RD. Whichever of hkl/uvw isn't snapped by a fiber match
# falls back to the canonical (symmetry-consistent) rational-fit index,
# same as before this fiber-snapping was added.
final_hkl, final_uvw = [], []
for i in range(n_grains):
    if is_classified[i]:
        ideal = IDEAL_COMPONENTS[best_component[i]]
        final_hkl.append(ideal["hkl"])
        final_uvw.append(ideal["uvw"])
        continue

    if fiber_mem_df["Lambda fiber <100>//ND"][i]:
        final_hkl.append(snap_to_family(ND_raw[i], "100"))
    elif fiber_mem_df["Gamma fiber <111>//ND"][i]:
        final_hkl.append(snap_to_family(ND_raw[i], "111"))
    else:
        final_hkl.append(canon_hkl_list[i])

    if fiber_mem_df["Eta fiber <001>//RD"][i]:
        final_uvw.append(snap_to_family(RD_raw[i], "100"))
    elif fiber_mem_df["Alpha fiber <110>//RD"][i]:
        final_uvw.append(snap_to_family(RD_raw[i], "110"))
    else:
        final_uvw.append(canon_uvw_list[i])

df_out = df[["phi1", "Phi", "phi2", "x", "y", "area", "diameter"]].copy()
df_out.insert(0, "grain_id", np.arange(1, n_grains + 1))

# The two columns requested: plain (hkl) and [uvw] strings, nothing else in them
df_out["hkl"] = [fmt_plain(t, "()") for t in final_hkl]
df_out["uvw"] = [fmt_plain(t, "[]") for t in final_uvw]

# Supporting columns kept separately (classification info, NOT inside hkl/uvw)
df_out["nearest_component"] = component_label
df_out["angle_to_nearest_component_deg"] = best_angle.round(2)
df_out["hkl_int"] = [",".join(str(v) for v in t) for t in final_hkl]
df_out["uvw_int"] = [",".join(str(v) for v in t) for t in final_uvw]

out_csv = os.path.join(OUT_DIR, "grain_hkl_uvw.csv")
df_out.to_csv(out_csv, index=False)
print(f"\n[Output 1] Per-grain hkl / uvw orientations written to: {out_csv}")
print(df_out[["grain_id", "phi1", "Phi", "phi2", "hkl", "uvw", "nearest_component"]].head(10).to_string(index=False))


# ----------------------------------------------------------------------
# 8. FRACTIONS (number-fraction and area-weighted fraction)
# ----------------------------------------------------------------------
area = df["area"].to_numpy()
total_area = area.sum()

print("\n" + "=" * 70)
print("[Output 2] TEXTURE COMPONENT / FIBER FRACTIONS")
print(f"(component tolerance = {TOL_COMPONENT} deg, fiber tolerance = {TOL_FIBER} deg)")
print("=" * 70)

print("\n--- Discrete texture components (each grain assigned to its")
print("    nearest component if within tolerance, else 'Other/Random') ---")
print(f"{'Component':30s}{'Number frac. (%)':>18s}{'Area frac. (%)':>18s}")
for name in list(IDEAL_COMPONENTS.keys()) + ["Other/Random"]:
    mask = component_label == name
    num_frac = 100.0 * mask.sum() / n_grains
    area_frac = 100.0 * area[mask].sum() / total_area
    print(f"{name:30s}{num_frac:18.2f}{area_frac:18.2f}")

print("\n--- Texture fibers (NOT mutually exclusive; a grain can lie on")
print("    more than one fiber at once, e.g. Cube lies on Lambda fiber) ---")
print(f"{'Fiber':30s}{'Number frac. (%)':>18s}{'Area frac. (%)':>18s}")
for name in FIBERS.keys():
    mask = fiber_mem_df[name].to_numpy()
    num_frac = 100.0 * mask.sum() / n_grains
    area_frac = 100.0 * area[mask].sum() / total_area
    print(f"{name:30s}{num_frac:18.2f}{area_frac:18.2f}")

# ----------------------------------------------------------------------
# 9. SAVE full per-grain classification table
# ----------------------------------------------------------------------
df_class = df_out.copy()
for name in FIBERS.keys():
    short = name.split()[0]
    df_class[f"on_{short}_fiber"] = fiber_mem_df[name].to_numpy()
    df_class[f"{short}_fiber_deviation_deg"] = fiber_dev_df[name].round(2).to_numpy()

out_csv2 = os.path.join(OUT_DIR, "grain_texture_classification.csv")
df_class.to_csv(out_csv2, index=False)
print(f"\nFull per-grain classification (components + fibers) written to:\n  {out_csv2}")