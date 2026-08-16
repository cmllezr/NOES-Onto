"""
EBSD Texture Analysis for Fe-3%Si Non-Oriented Electrical Steel
=================================================================

Uses the `orix` package (https://orix.readthedocs.io) to:

  1. Compute, for every indexed grain, the misorientation angle between
     its measured orientation and each of the 8 ideal texture
     orientations (the 4 point components below, via full-symmetry
     disorientation; the 4 fibers, via axis-deviation angle) -- these
     angles are exactly what the NOES ontology's misorientation-angle
     based texture classification axioms (crystallite -> has relational
     quality -> misorientation angle -> relational quality of -> ideal
     texture individual) consume downstream.
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
"""

import os
import numpy as np
import pandas as pd
from orix.quaternion import Orientation, symmetry

# ----------------------------------------------------------------------
# USER-ADJUSTABLE PARAMETERS
# ----------------------------------------------------------------------
DATA_FILE = "../EBSD.txt"
OUT_DIR = "../"

TOL_COMPONENT = 15.0   # deg, max disorientation to an ideal texture component
TOL_FIBER = 15.0       # deg, max deviation of the fiber axis from ND / RD

CRYSTAL_SYMMETRY = symmetry.Oh   # m-3m, correct Laue class for ferrite (BCC-Fe, cubic)

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


# Keyed by the same slugs used downstream by ebsd2rdf.py's TEXTURE_SLUGS /
# IDEAL_GRAIN_TYPES, so the misorientation columns built in section 5 line
# up 1:1 with the ontology classes they'll be staged against.
IDEAL_COMPONENTS = {
    "cube":          {"label": "Cube {001}<100>",          "hkl": (0, 0, 1), "uvw": (1, 0, 0)},
    "goss":          {"label": "Goss {110}<001>",          "hkl": (1, 1, 0), "uvw": (0, 0, 1)},
    "rotated_cube":  {"label": "Rotated Cube {001}<110>",  "hkl": (0, 0, 1), "uvw": (1, 1, 0)},
    "rotated_goss":  {"label": "Rotated Goss {110}<1-10>", "hkl": (1, 1, 0), "uvw": (1, -1, 0)},
}
IDEAL_ORIENTATIONS = {
    slug: orientation_from_hkl_uvw(v["hkl"], v["uvw"])
    for slug, v in IDEAL_COMPONENTS.items()
}

# Disorientation of every grain to every ideal component (crystal symmetry
# equivalents are automatically searched by orix because both `ori` and the
# ideal orientations carry symmetry=Oh). This IS the misorientation angle
# the ontology's texture-classification axioms consume (NOES_0000141).
angles_to_component = {}
for slug, ideal in IDEAL_ORIENTATIONS.items():
    ang = ideal.angle_with_outer(ori, degrees=True)[0]  # shape (n_grains,)
    angles_to_component[slug] = ang

comp_angle_df = pd.DataFrame(angles_to_component)
best_component = comp_angle_df.idxmin(axis=1)
best_angle = comp_angle_df.min(axis=1)
is_classified = best_angle <= TOL_COMPONENT
component_label = np.where(is_classified, best_component, "Other/Random")


# ----------------------------------------------------------------------
# 4. FIBER CLASSIFICATION
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


# Keyed by the fiber slugs from ebsd2rdf.py's TEXTURE_SLUGS (alpha, gamma,
# eta, lambda), each mapped to its sample-frame axis and crystal family.
FIBERS = {
    "lambda": {"label": "Lambda fiber <100>//ND", "sample_dir": ND_raw, "family": "100"},
    "gamma":  {"label": "Gamma fiber <111>//ND",  "sample_dir": ND_raw, "family": "111"},
    "eta":    {"label": "Eta fiber <001>//RD",    "sample_dir": RD_raw, "family": "100"},  # <001> is a member of <100>
    "alpha":  {"label": "Alpha fiber <110>//RD",  "sample_dir": RD_raw, "family": "110"},
}

fiber_membership = {}
fiber_deviation = {}
for slug, spec in FIBERS.items():
    dev = min_angle_to_family(spec["sample_dir"], family_directions(spec["family"]))
    fiber_deviation[slug] = dev
    fiber_membership[slug] = dev <= TOL_FIBER

fiber_dev_df = pd.DataFrame(fiber_deviation)
fiber_mem_df = pd.DataFrame(fiber_membership)

# ----------------------------------------------------------------------
# 5. BUILD PER-GRAIN MISORIENTATION-ANGLE COLUMNS (ontology-ready)
# ----------------------------------------------------------------------
# One column per ideal texture (4 point components + 4 fibers), in the
# same slug order as ebsd2rdf.py's TEXTURE_SLUGS/IDEAL_GRAIN_TYPES, plus
# an `is_relevant` flag (true if the grain is within tolerance of *any*
# of the 8 ideal textures) that ebsd2rdf.py's --relevant-only flag can
# use to skip staging misorientation triples for grains nowhere near any
# named texture.
TEXTURE_SLUGS = ["cube", "goss", "rotated_cube", "rotated_goss", "alpha", "gamma", "eta", "lambda"]

df_out = df[["phi1", "Phi", "phi2", "x", "y", "area", "diameter"]].copy()
df_out.insert(0, "grain_id", np.arange(1, n_grains + 1))

is_relevant = np.zeros(n_grains, dtype=bool)
for slug in TEXTURE_SLUGS:
    if slug in angles_to_component:
        angle = angles_to_component[slug]
        tol = TOL_COMPONENT
    else:
        angle = fiber_deviation[slug]
        tol = TOL_FIBER
    df_out[f"misorientation_{slug}_deg"] = np.round(angle, 4)
    is_relevant |= angle <= tol

df_out["is_relevant"] = is_relevant
df_out["nearest_component"] = component_label
df_out["angle_to_nearest_component_deg"] = best_angle.round(2)

out_csv = os.path.join(OUT_DIR, "grain_misorientation.csv")
df_out.to_csv(out_csv, index=False)
print(f"\n[Output 1] Per-grain misorientation angles written to: {out_csv}")
misorientation_cols = [f"misorientation_{slug}_deg" for slug in TEXTURE_SLUGS]
print(df_out[["grain_id", "phi1", "Phi", "phi2", "nearest_component", "is_relevant"] + misorientation_cols].head(10).to_string(index=False))


# ----------------------------------------------------------------------
# 6. FRACTIONS (number-fraction and area-weighted fraction)
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
for slug in list(IDEAL_COMPONENTS.keys()) + ["Other/Random"]:
    label = IDEAL_COMPONENTS[slug]["label"] if slug in IDEAL_COMPONENTS else slug
    mask = component_label == slug
    num_frac = 100.0 * mask.sum() / n_grains
    area_frac = 100.0 * area[mask].sum() / total_area
    print(f"{label:30s}{num_frac:18.2f}{area_frac:18.2f}")

print("\n--- Texture fibers (NOT mutually exclusive; a grain can lie on")
print("    more than one fiber at once, e.g. Cube lies on Lambda fiber) ---")
print(f"{'Fiber':30s}{'Number frac. (%)':>18s}{'Area frac. (%)':>18s}")
for slug, spec in FIBERS.items():
    mask = fiber_mem_df[slug].to_numpy()
    num_frac = 100.0 * mask.sum() / n_grains
    area_frac = 100.0 * area[mask].sum() / total_area
    print(f"{spec['label']:30s}{num_frac:18.2f}{area_frac:18.2f}")

# ----------------------------------------------------------------------
# 7. SAVE full per-grain classification table
# ----------------------------------------------------------------------
df_class = df_out.copy()
for slug in FIBERS.keys():
    df_class[f"on_{slug}_fiber"] = fiber_mem_df[slug].to_numpy()
    df_class[f"{slug}_fiber_deviation_deg"] = fiber_dev_df[slug].round(2).to_numpy()

out_csv2 = os.path.join(OUT_DIR, "grain_texture_classification.csv")
df_class.to_csv(out_csv2, index=False)
print(f"\nFull per-grain classification (components + fibers) written to:\n  {out_csv2}")