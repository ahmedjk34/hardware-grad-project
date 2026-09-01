#!/usr/bin/env python3
"""Software colour correction: one affine BGR transform, saved with the camera.

Why this exists
---------------
The rig's camera does not agree with anyone's eyes. A live frame arrived with a
magenta cast strong enough to turn the printed sheet's green ink cyan, which
made half of it invisible to ``vision/color_grid.py`` and degrades
``vision/block_detector.py`` too, since that keys on red-minus-blue. The
detectors can defend themselves — ``color_grid`` white balances internally —
but defending each consumer separately is the wrong shape. Fix the picture once,
where the picture is defined, and every stage downstream inherits it.

So this is a small transform that lives in ``camera_settings.json`` next to the
lens block, is edited in ``camera_studio.py``'s COLOUR section, and is applied
by ``camera_feed.py`` and everything built on it.

The model
---------
One 3x4 affine matrix in **BGR**, then gamma, then saturation::

    out = clip(M[:, :3] @ bgr + M[:, 3])
    out = 255 * (out / 255) ** (1 / gamma)
    out = luma + saturation * (out - luma)

The matrix covers the two things a camera actually gets wrong: per-channel gain
(white balance) on the diagonal, and cross-channel bleed off it. A diagonal
matrix is the common case and is the default a calibration solves for, because
it is over-determined by the samples available and therefore stable. The full
3x3 is offered for when the diagonal visibly cannot get there, and is flagged
when solved, because three ink colours determine it exactly with nothing left
over to check it against.

Gamma and saturation are separate rather than folded in because they are not
linear, and because they are the two knobs a person reaches for after the
neutral is right.

How a calibration is solved
---------------------------
Photograph the printed calibration sheet twice: once with something you trust
(a phone), once with the rig camera. ``vision/color_grid.py`` finds the sheet in
both, so each image yields the mean colour of its green ink, its magenta ink and
its white paper. Those three pairs are what the least squares fits.

Matching is by **ink identity, not by cell index**, on purpose. The two photos
will generally frame different parts of an oversized sheet, so ``[3,2]`` in one
is not the same physical block as ``[3,2]`` in the other — but every green cell
is the same green, so the pairing that matters survives.

Three colours is few. The residual is reported for exactly that reason: a fit
that cannot even reproduce the three colours it was given is not going to
reproduce anything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import cv2
import numpy as np

# Channel order everywhere in this module, matching OpenCV.
CHANNELS = ("blue", "green", "red")

GAMMA_RANGE = (0.2, 5.0)
SATURATION_RANGE = (0.0, 3.0)
GAIN_RANGE = (0.05, 8.0)
OFFSET_RANGE = (-128.0, 128.0)

# Below this the transform is close enough to identity that applying it would
# cost a frame copy for no visible change.
_IDENTITY_TOLERANCE = 1e-3

IDENTITY = np.hstack([np.eye(3), np.zeros((3, 1))])


class ColorCorrectionError(Exception):
    """A calibration could not be solved from what was supplied."""


def _clamp(value, low, high):
    return min(max(float(value), low), high)


@dataclass
class ColorCorrection:
    """An affine BGR correction plus gamma and saturation.

    Construct from :meth:`from_settings`, edit through the setters so a value
    can never be stored outside its range, and apply with :meth:`apply`.
    """

    enabled: bool = False
    matrix: np.ndarray = field(default_factory=lambda: IDENTITY.copy())
    gamma: float = 1.0
    saturation: float = 1.0
    source: str = ""

    def __post_init__(self):
        self.matrix = np.asarray(self.matrix, dtype=np.float64).reshape(3, 4)
        self.gamma = _clamp(self.gamma, *GAMMA_RANGE)
        self.saturation = _clamp(self.saturation, *SATURATION_RANGE)
        self._cache = None

    # --- the parts a person edits -----------------------------------------

    @property
    def gain(self) -> tuple[float, float, float]:
        """The matrix diagonal, in BGR. This is the white balance."""
        return tuple(float(self.matrix[i, i]) for i in range(3))

    @property
    def offset(self) -> tuple[float, float, float]:
        """The matrix's last column, in BGR. This is the black level."""
        return tuple(float(self.matrix[i, 3]) for i in range(3))

    @property
    def mix(self) -> float:
        """How much cross-channel bleed the matrix carries, 0 for a diagonal one.

        Reported rather than edited: nobody tunes an off-diagonal term by hand,
        but knowing whether one is present explains why the gain fields alone do
        not describe what is happening to the picture.
        """
        off = self.matrix[:, :3] - np.diag(np.diag(self.matrix[:, :3]))
        return float(np.abs(off).max())

    @property
    def is_diagonal(self) -> bool:
        return self.mix <= _IDENTITY_TOLERANCE

    def set_gain(self, channel: int, value: float) -> float:
        self.matrix[channel, channel] = _clamp(value, *GAIN_RANGE)
        self._cache = None
        return float(self.matrix[channel, channel])

    def set_offset(self, channel: int, value: float) -> float:
        self.matrix[channel, 3] = _clamp(value, *OFFSET_RANGE)
        self._cache = None
        return float(self.matrix[channel, 3])

    def set_gamma(self, value: float) -> float:
        self.gamma = _clamp(value, *GAMMA_RANGE)
        self._cache = None
        return self.gamma

    def set_saturation(self, value: float) -> float:
        self.saturation = _clamp(value, *SATURATION_RANGE)
        self._cache = None
        return self.saturation

    def set_matrix(self, matrix, source: str = "") -> "ColorCorrection":
        self.matrix = np.asarray(matrix, dtype=np.float64).reshape(3, 4)
        self.source = source
        self._cache = None
        return self

    def drop_mix(self) -> float:
        """Throw away the off-diagonal terms, keeping the gains and offsets.

        The escape hatch for a full-matrix fit that looks worse than it
        measured: three ink colours pin a 3x3 exactly, so a bad sample can
        rotate hues with nothing to contradict it, and this returns to the
        white-balance-only correction without losing the neutral it found.
        """
        removed = self.mix
        linear = np.diag(np.diag(self.matrix[:, :3]))
        self.matrix = np.hstack([linear, self.matrix[:, 3:4]])
        self._cache = None
        return removed

    def reset(self) -> "ColorCorrection":
        self.matrix = IDENTITY.copy()
        self.gamma = 1.0
        self.saturation = 1.0
        self.source = ""
        self._cache = None
        return self

    # --- applying it -------------------------------------------------------

    @property
    def is_identity(self) -> bool:
        return (abs(self.gamma - 1.0) <= _IDENTITY_TOLERANCE
                and abs(self.saturation - 1.0) <= _IDENTITY_TOLERANCE
                and np.allclose(self.matrix, IDENTITY, atol=_IDENTITY_TOLERANCE))

    def _lut(self):
        """A 256x3 table for the diagonal-plus-gamma case, built once.

        Worth the special case: that is what a white balance is, it is what most
        saved corrections will be, and a table lookup is several times cheaper
        than a matrix transform on a Pi.
        """
        if self._cache is None:
            ramp = np.arange(256, dtype=np.float64)
            table = np.empty((3, 256), dtype=np.uint8)
            for index in range(3):
                values = ramp * self.matrix[index, index] + self.matrix[index, 3]
                values = np.clip(values, 0, 255)
                if abs(self.gamma - 1.0) > _IDENTITY_TOLERANCE:
                    values = 255.0 * np.power(values / 255.0, 1.0 / self.gamma)
                table[index] = np.clip(values, 0, 255).astype(np.uint8)
            self._cache = np.ascontiguousarray(table.T.reshape(1, 256, 3))
        return self._cache

    def apply(self, frame: np.ndarray) -> np.ndarray:
        """Return a corrected copy, or the frame itself when there is nothing to do.

        Returning the input unchanged for an identity correction is deliberate:
        it keeps ``correction.apply(frame)`` free to sit unconditionally in
        every pipeline, so no caller has to remember to check ``enabled``.
        """
        if frame is None or not self.enabled or self.is_identity:
            return frame
        if self.is_diagonal:
            out = cv2.LUT(frame, self._lut())
        else:
            out = cv2.transform(frame, self.matrix)
            if abs(self.gamma - 1.0) > _IDENTITY_TOLERANCE:
                ramp = np.arange(256, dtype=np.float64) / 255.0
                gamma_lut = np.clip(255.0 * np.power(ramp, 1.0 / self.gamma),
                                    0, 255).astype(np.uint8)
                out = cv2.LUT(out, gamma_lut)
        if abs(self.saturation - 1.0) > _IDENTITY_TOLERANCE:
            grey = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
            grey = cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR)
            out = cv2.addWeighted(out, self.saturation, grey,
                                  1.0 - self.saturation, 0.0)
        return out

    def implausibilities(self) -> list[str]:
        """Ways this transform does not look like a camera correction.

        The residual only measures the three colours the fit was given, and on
        real data it ranks the fits *backwards*: the full 3x3 scores a perfect
        zero while turning the wall behind the rig bright pink, because nothing
        in the samples constrains it out there. So the check has to be on the
        coefficients rather than on the fit error.

        (A mid-grey probe was tried first and is not usable: correcting a real
        cast is *supposed* to move grey, so it flags the good fit and passes the
        bad one. What actually separates them is negative gains, offsets that
        only an extrapolation would choose, and cross-channel terms as large as
        the channels themselves.)
        """
        problems = []
        diagonal = np.diag(self.matrix[:, :3])
        if diagonal.min() <= 0:
            problems.append(
                f"the {CHANNELS[int(np.argmin(diagonal))]} gain is "
                f"{diagonal.min():+.2f} — a negative gain inverts that channel "
                f"and is never a real camera correction")
        worst_offset = float(np.abs(self.matrix[:, 3]).max())
        if worst_offset > SUSPICIOUS_OFFSET:
            problems.append(
                f"an offset reaches {worst_offset:.0f} levels, far outside the "
                f"brightness range the sheet could measure")
        scale = float(np.abs(diagonal).max())
        if scale > 1e-6 and self.mix > 0.5 * scale:
            problems.append(
                f"cross-channel mixing ({self.mix:.2f}) is comparable to the "
                f"gains themselves ({scale:.2f}); hues far from the sheet's own "
                f"will be moved arbitrarily")
        return problems

    # --- persistence -------------------------------------------------------

    @classmethod
    def from_settings(cls, data: dict | None) -> "ColorCorrection":
        """Read the ``colour`` block of a camera settings file.

        Tolerant like the rest of that file: a missing or partial block is an
        identity correction, not an error. A settings file written before this
        existed must still load.
        """
        block = (data or {}).get("colour") or {}
        matrix = block.get("matrix")
        if matrix is None:
            gain = block.get("gain", (1.0, 1.0, 1.0))
            offset = block.get("offset", (0.0, 0.0, 0.0))
            try:
                matrix = np.hstack([np.diag([float(v) for v in gain]),
                                    np.asarray([[float(v)] for v in offset])])
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "camera settings: colour.gain/offset must each be three "
                    "numbers in BGR order") from exc
        else:
            try:
                matrix = np.asarray(matrix, dtype=np.float64).reshape(3, 4)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "camera settings: colour.matrix must be 3x4 (BGR affine)") from exc
        return cls(
            enabled=bool(block.get("enabled", False)),
            matrix=matrix,
            gamma=float(block.get("gamma", 1.0)),
            saturation=float(block.get("saturation", 1.0)),
            source=str(block.get("source", "")),
        )

    def to_settings(self) -> dict:
        """The ``colour`` block, with gain/offset written out for readability.

        Both forms are stored. ``matrix`` is what loads; ``gain`` and ``offset``
        are its diagonal and its last column, present so the file can be read by
        a person without doing matrix algebra in their head. ``from_settings``
        ignores them whenever a matrix is there, so they cannot drift into being
        a second source of truth.
        """
        return {
            "enabled": bool(self.enabled),
            "matrix": [[round(v, 6) for v in row] for row in self.matrix],
            "gain": [round(v, 5) for v in self.gain],
            "offset": [round(v, 4) for v in self.offset],
            "gamma": round(self.gamma, 4),
            "saturation": round(self.saturation, 4),
            "source": self.source,
        }

    # --- reporting ---------------------------------------------------------

    def describe(self) -> str:
        state = "on" if self.enabled else "off"
        if self.is_identity:
            return f"colour {state}, identity"
        blue, green, red = self.gain
        text = (f"colour {state}, gain B{blue:.3f} G{green:.3f} R{red:.3f}"
                f", gamma {self.gamma:.2f}, sat {self.saturation:.2f}")
        if not self.is_diagonal:
            text += f", mix {self.mix:+.3f}"
        return text


# ---------------------------------------------------------------------------
# solving one from measurements
# ---------------------------------------------------------------------------


# The three shapes a calibration can take, cheapest and safest first.
#
#   gain    per-channel gain through the origin. Three numbers. This IS a white
#           balance, it cannot crush blacks, and it is over-determined by the
#           sheet's three colours. The default, and almost always the answer.
#   affine  gain plus a per-channel offset. Six numbers. Also corrects black
#           level and overall brightness — but the sheet's colours are all
#           bright, so the line down to black is an extrapolation and the fit
#           will happily choose an offset near -200 to buy a slightly better
#           match on paper. Watch for that; `solve_matrix` reports it.
#   matrix  full linear 3x3, no offset. Nine numbers, exactly determined by
#           three colours, so it reproduces them perfectly whether or not it is
#           right about anything else. For when the diagonal visibly cannot get
#           there, and reversible with `ColorCorrection.drop_mix()`.
FIT_MODES = ("gain", "affine", "matrix")
DEFAULT_FIT_MODE = "gain"

# An offset past this is a sign the fit extrapolated rather than measured.
SUSPICIOUS_OFFSET = 40.0



def solve_matrix(camera_colors, reference_colors, *, mode=DEFAULT_FIT_MODE):
    """Least-squares BGR transform taking camera colours to reference ones.

    ``camera_colors`` and ``reference_colors`` are matching Nx3 arrays; see
    :data:`FIT_MODES` for what each mode fits and why the default is the
    smallest one. Returns ``(matrix, residual, notes)``: the residual is the RMS
    error in 0..255 levels after the fit, and ``notes`` holds any warnings worth
    putting in front of whoever pressed the button.

    A low residual is necessary and not sufficient. With three colours the
    richer fits can drive it to zero by contorting themselves, which is exactly
    what the notes are for.
    """
    if mode not in FIT_MODES:
        raise ColorCorrectionError(
            f"fit mode must be one of {', '.join(FIT_MODES)}, not {mode!r}")
    camera = np.asarray(camera_colors, dtype=np.float64).reshape(-1, 3)
    reference = np.asarray(reference_colors, dtype=np.float64).reshape(-1, 3)
    if camera.shape != reference.shape:
        raise ColorCorrectionError(
            f"{len(camera)} camera colours against {len(reference)} reference "
            f"colours; they have to pair up")
    samples = len(camera)
    minimum = {"gain": 1, "affine": 2, "matrix": 3}[mode]
    if samples < minimum:
        raise ColorCorrectionError(
            f"{samples} paired colour(s) is not enough for the {mode} fit; "
            f"{minimum} are needed")

    matrix = np.zeros((3, 4))
    notes = []
    if mode == "matrix":
        if np.linalg.matrix_rank(camera) < 3:
            raise ColorCorrectionError(
                "the sampled colours are not independent enough for a full "
                "matrix; use the gain fit instead")
        solution, *_ = np.linalg.lstsq(camera, reference, rcond=None)
        matrix[:, :3] = solution.T
        if samples <= 3:
            notes.append("a 3x3 from 3 colours is exactly determined: the "
                         "residual proves nothing, so judge it by eye")
    else:
        for index in range(3):
            column = camera[:, index]
            if mode == "affine":
                design = np.column_stack([column, np.ones(samples)])
                solution, *_ = np.linalg.lstsq(design, reference[:, index],
                                               rcond=None)
                matrix[index, index], matrix[index, 3] = solution
            else:
                denominator = float(column @ column)
                if denominator < 1e-9:
                    raise ColorCorrectionError(
                        f"the {CHANNELS[index]} channel is black in every "
                        f"sample; there is nothing to scale")
                matrix[index, index] = float(column @ reference[:, index]) / denominator

    predicted = camera @ matrix[:, :3].T + matrix[:, 3]
    residual = float(np.sqrt(np.mean((predicted - reference) ** 2)))

    notes.extend(ColorCorrection(matrix=matrix).implausibilities())
    return matrix, residual, notes


def neutral_matrix(white_bgr, target=None):
    """Per-channel gains that turn one measured colour neutral.

    The one-sample case, kept separate from :func:`solve_matrix` because it is
    a different question: not "match this reference" but "make this grey", which
    needs no reference photo at all — just something in shot that ought to be
    white. On the calibration sheet, that is the paper.
    """
    white = np.asarray(white_bgr, dtype=np.float64).reshape(3)
    if not np.all(np.isfinite(white)) or white.min() <= 1.0:
        raise ColorCorrectionError(
            "the white reference is black or unreadable; point at something "
            "lit and pale")
    level = float(np.mean(white)) if target is None else float(target)
    gains = np.clip(level / white, *GAIN_RANGE)
    return np.hstack([np.diag(gains), np.zeros((3, 1))])


def equivalent_sensor_gains(matrix, white_bgr) -> tuple[float, float]:
    """The camera's own red/blue gains that would do the same job.

    A software matrix is applied after the sensor has already thrown away
    headroom in whichever channel it under-exposed. Pushing the same correction
    into ``redgain``/``bluegain`` fixes it before that happens, which is
    strictly better when the backend supports it — so a calibration reports
    these alongside the matrix rather than pretending software is the only
    option. Relative to green, because that is how the controls are defined.

    Measured as the transform's *effective* ratio at ``white_bgr``, never from
    the matrix diagonal. Once offsets are involved the diagonal is not the gain:
    a fit can pair a gain of 2.3 with an offset of -207 and end up darkening the
    channel it appears to be doubling.
    """
    matrix = np.asarray(matrix, dtype=np.float64).reshape(3, 4)
    white = np.asarray(white_bgr, dtype=np.float64).reshape(3)
    if white.min() <= 1.0:
        raise ColorCorrectionError(
            "the white reference is black; nothing to measure a ratio against")
    ratio = (matrix[:, :3] @ white + matrix[:, 3]) / white
    if abs(ratio[1]) < 1e-6:
        raise ColorCorrectionError("the green channel maps to zero here")
    return float(ratio[2] / ratio[1]), float(ratio[0] / ratio[1])


@dataclass
class ColorSamples:
    """The mean colour of each thing on the sheet, and how consistent it was."""

    colors: dict          # name -> (b, g, r)
    counts: dict          # name -> how many patches were averaged
    spread: dict          # name -> RMS distance of patches from their mean

    @property
    def names(self) -> tuple:
        return tuple(sorted(self.colors))

    def describe(self) -> str:
        return " | ".join(
            f"{name} ({self.colors[name][2]:.0f},{self.colors[name][1]:.0f},"
            f"{self.colors[name][0]:.0f}) n={self.counts[name]} "
            f"spread {self.spread[name]:.1f}"
            for name in self.names)


def pair_samples(camera: ColorSamples, reference: ColorSamples):
    """Match two sample sets by ink identity and return (camera, reference) Nx3.

    By name, never by cell index: the two photos frame different parts of an
    oversized sheet, so their ``[col,row]`` grids are not the same physical
    cells — but green is green in both.
    """
    shared = [name for name in camera.names if name in reference.colors]
    if len(shared) < 2:
        raise ColorCorrectionError(
            f"only {len(shared)} colour(s) appear in both images "
            f"({', '.join(shared) or 'none'}); the sheet has to be detected in each")
    return (np.array([camera.colors[name] for name in shared]),
            np.array([reference.colors[name] for name in shared]),
            shared)


# ---------------------------------------------------------------------------
# tuning a whole correction against a trusted photograph
# ---------------------------------------------------------------------------
#
# solve_matrix above pairs a handful of measured ink colours. The functions
# here pair the colour DISTRIBUTIONS of two whole frames instead, so they work
# when the live view and the reference photo do not frame the same thing — a
# blurred crop of the rig against a sharp phone shot of the same sheet, which is
# exactly the pair captures/color_correction/ holds. Same model, same
# ColorCorrection object, same settings block: this is another way to solve one,
# not a second pipeline.


# Newly crushed-or-blown pixels past this fraction of the frame mean the
# transform is destroying detail rather than correcting colour.
MAX_NEW_CLIPPING = 0.02


def color_similarity(image_a, image_b) -> float:
    """A 0..1 score for how alike two frames are in COLOUR, framing aside.

    Built from three views that a colour cast moves and that a crop or a soft
    focus mostly leave alone:

      * the spread of hues, a 2-D histogram of the CIELAB a*/b* plane;
      * the spread of brightness, a 1-D grey histogram;
      * the first two moments (mean and standard deviation) of each BGR channel.

    1.0 is identical colour. Because the metric ignores where things are, two
    photographs of the same sheet from different distances still score high once
    the cast between them is gone — which is what makes it usable as the thing
    :func:`tune_to_reference` maximises. Reported in Camera Studio as the
    "match to raw phone" percentage.
    """
    a = np.asarray(image_a)
    b = np.asarray(image_b)
    if a.ndim != 3 or b.ndim != 3 or a.shape[2] != 3 or b.shape[2] != 3:
        raise ColorCorrectionError("colour similarity needs two BGR images")

    def chroma_hist(img):
        lab = cv2.cvtColor(np.ascontiguousarray(img), cv2.COLOR_BGR2LAB)
        hist = cv2.calcHist([lab], [1, 2], None, [24, 24], [0, 256, 0, 256])
        total = float(hist.sum())
        return hist / total if total else hist

    def grey_hist(img):
        grey = cv2.cvtColor(np.ascontiguousarray(img), cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([grey], [0], None, [32], [0, 256])
        total = float(hist.sum())
        return hist / total if total else hist

    chroma_score = float(np.minimum(chroma_hist(a), chroma_hist(b)).sum())
    grey_score = float(np.minimum(grey_hist(a), grey_hist(b)).sum())

    flat_a = a.reshape(-1, 3).astype(np.float64)
    flat_b = b.reshape(-1, 3).astype(np.float64)
    mean_err = float(np.abs(flat_a.mean(0) - flat_b.mean(0)).mean())
    std_err = float(np.abs(flat_a.std(0) - flat_b.std(0)).mean())
    moment_score = math.exp(-(mean_err + std_err) / 25.0)

    score = 0.5 * chroma_score + 0.2 * grey_score + 0.3 * moment_score
    return float(min(1.0, max(0.0, score)))


def _distribution_moments(pixels):
    flat = np.asarray(pixels, dtype=np.float64).reshape(-1, 3)
    if len(flat) < 2:
        raise ColorCorrectionError(
            "a colour distribution needs at least two pixels to measure")
    return flat.mean(0), np.cov(flat, rowvar=False)


def _psd_power(matrix, power):
    """``matrix ** power`` for a symmetric positive-semidefinite matrix.

    Via the eigendecomposition, with the eigenvalues floored so a flat channel
    cannot send an inverse power to infinity.
    """
    symmetric = (np.asarray(matrix, dtype=np.float64) + np.asarray(matrix).T) / 2.0
    values, vectors = np.linalg.eigh(symmetric)
    values = np.clip(values, 1e-10, None)
    return (vectors * (values ** power)) @ vectors.T


def solve_distribution_transfer(camera_image, reference_image,
                                *, mode=DEFAULT_FIT_MODE):
    """A BGR transform matching one frame's colour distribution to another's.

    Where :func:`solve_matrix` pairs measured ink colours, this pairs the
    distributions: it lines up the mean and covariance of the camera colour
    cloud with the reference's. No correspondence between the frames is needed,
    so they may be different crops of the sheet, or one may be soft.

    ``mode`` mirrors :data:`FIT_MODES`:

      gain    per-channel scale through each channel's mean — a white balance.
      affine  per-channel scale (matched on spread) plus offset.
      matrix  the full linear map carrying the camera cloud onto the reference
              one: the closed-form linear Monge-Kantorovich solution, i.e.
              gains, offsets and cross-channel mixing solved together.

    Returns ``(matrix, notes)`` like :func:`solve_matrix`. There is no residual:
    the fit is exact on the moments by construction, so the honest check is
    :func:`color_similarity` on the corrected frame, not a number here. ``notes``
    still carries :meth:`ColorCorrection.implausibilities` — for the full matrix
    the mean-recentring offset is large by design and shows up there.
    """
    if mode not in FIT_MODES:
        raise ColorCorrectionError(
            f"fit mode must be one of {', '.join(FIT_MODES)}, not {mode!r}")

    cam_mean, cam_cov = _distribution_moments(camera_image)
    ref_mean, ref_cov = _distribution_moments(reference_image)
    cam_var = np.clip(np.diag(cam_cov), 1e-8, None)
    ref_var = np.clip(np.diag(ref_cov), 1e-8, None)

    if mode == "gain":
        gains = np.clip(ref_mean / np.clip(cam_mean, 1e-6, None), *GAIN_RANGE)
        linear = np.diag(gains)
        offset = np.zeros(3)
    elif mode == "affine":
        gains = np.clip(np.sqrt(ref_var / cam_var), *GAIN_RANGE)
        linear = np.diag(gains)
        offset = ref_mean - linear @ cam_mean
    else:
        cam_sqrt = _psd_power(cam_cov, 0.5)
        cam_isqrt = _psd_power(cam_cov, -0.5)
        middle = _psd_power(cam_sqrt @ ref_cov @ cam_sqrt, 0.5)
        linear = cam_isqrt @ middle @ cam_isqrt
        offset = ref_mean - linear @ cam_mean

    matrix = np.hstack([np.asarray(linear, dtype=np.float64), offset.reshape(3, 1)])
    notes = ColorCorrection(matrix=matrix).implausibilities()
    return matrix, notes


@dataclass
class TuningResult:
    """What :func:`tune_to_reference` found, and how far it got.

    ``correction`` is always usable; ``passed`` says whether ``target`` was
    actually reached, and ``notes`` records every compromise made on the way —
    a fit rejected as unsafe, a score that did not beat the untouched frame,
    the large offset the full matrix carries.
    """

    correction: "ColorCorrection"
    similarity: float
    baseline: float
    iterations: int
    clipping: float
    notes: list
    passed: bool

    def summary(self) -> str:
        state = "target reached" if self.passed else "best safe result"
        return (f"{self.similarity * 100:.1f}% colour similarity ({state}), "
                f"up from {self.baseline * 100:.1f}%, after {self.iterations} "
                f"tone iteration(s); {self.clipping * 100:.2f}% newly clipped")


def _new_clipping(before, after):
    was = (before == 0).any(2) | (before == 255).any(2)
    now = (after == 0).any(2) | (after == 255).any(2)
    return float((now & ~was).mean())


def _neutral_ramp():
    ramp = np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2)
    return np.ascontiguousarray(np.repeat(ramp, 2, axis=0))


def _hard_faults(correction, corrected, clipping):
    """The ways a tuned correction is not safe to apply, as opposed to merely
    imperfect. Kept separate from :meth:`ColorCorrection.implausibilities`,
    which flags fits that *measure* well and look wrong; these are operational —
    an inverted channel, a blown frame, a non-monotone response.
    """
    faults = []
    if not np.all(np.isfinite(correction.matrix)):
        faults.append("the matrix has non-finite entries")
    diagonal = np.diag(correction.matrix[:, :3])
    if diagonal.min() <= 0:
        faults.append(f"the {CHANNELS[int(np.argmin(diagonal))]} gain is not positive")
    if clipping > MAX_NEW_CLIPPING:
        faults.append(f"{clipping * 100:.1f}% of the frame is newly clipped")
    mapped = correction.apply(_neutral_ramp())[0].astype(int)
    for index in range(3):
        if np.mean(np.diff(mapped[:, index]) >= 0) < 0.95:
            faults.append(
                f"the {CHANNELS[index]} channel is not monotone on a neutral ramp")
    return faults


def _refine_tone(correction, camera, reference, target, max_iterations):
    """Pattern search on gamma then saturation, shrinking the step when stuck.

    Gains, offsets and mixing are already fixed by the distribution transfer;
    these are the two non-linear knobs a person reaches for afterwards, and
    hill-climbing them on :func:`color_similarity` is deterministic and cheap.
    """
    score = color_similarity(correction.apply(camera), reference)
    gamma_step = saturation_step = 0.4
    iterations = 0
    while (iterations < max_iterations and score < target
           and (gamma_step > 0.02 or saturation_step > 0.02)):
        iterations += 1
        improved = False
        for setter, current, step in (
                (correction.set_gamma, correction.gamma, gamma_step),
                (correction.set_saturation, correction.saturation, saturation_step)):
            for candidate in (current + step, current - step):
                setter(candidate)
                trial = color_similarity(correction.apply(camera), reference)
                if trial > score + 1e-5:
                    score = trial
                    improved = True
                    break
                setter(current)
        if not improved:
            gamma_step *= 0.5
            saturation_step *= 0.5
    return iterations


def tune_to_reference(camera_image, reference_image, *, mode="matrix",
                      target=0.95, max_iterations=12):
    """Fit, then refine, a full :class:`ColorCorrection` taking a live view to a
    trusted photograph of the same scene.

    The whole process, run to completion:

      1. solve the distribution transfer (:func:`solve_distribution_transfer`) —
         gains, offsets and cross-channel mixing in one closed-form step;
      2. walk gamma, then saturation, by pattern search, each step scored by
         :func:`color_similarity` against the reference;
      3. stop when the score clears ``target``, stalls, or ``max_iterations``
         is spent, keeping the best correction seen;
      4. validate with :func:`_hard_faults`: nothing non-finite, no channel
         inverted, the neutral ramp still monotone, and no more than
         :data:`MAX_NEW_CLIPPING` of the frame newly crushed or blown. If the
         requested fit fails a hard check, fall back to ``affine`` then ``gain``
         and take the first that is safe.

    Returns a :class:`TuningResult`.
    """
    camera = np.ascontiguousarray(np.asarray(camera_image))
    reference = np.ascontiguousarray(np.asarray(reference_image))
    if camera.ndim != 3 or reference.ndim != 3:
        raise ColorCorrectionError("tuning needs two BGR images")

    baseline = color_similarity(camera, reference)
    notes = []
    attempts = [mode] + [m for m in ("affine", "gain") if m != mode]
    chosen = None
    for attempt in attempts:
        matrix, solve_notes = solve_distribution_transfer(camera, reference, mode=attempt)
        correction = ColorCorrection(enabled=True, matrix=matrix,
                                     source=f"tuned to reference, {attempt} fit")
        iterations = _refine_tone(correction, camera, reference, target, max_iterations)
        corrected = correction.apply(camera)
        clipping = _new_clipping(camera, corrected)
        faults = _hard_faults(correction, corrected, clipping)
        similarity = color_similarity(corrected, reference)
        record = (correction, similarity, iterations, clipping, faults, solve_notes)
        if not faults:
            chosen = record
            if attempt != mode:
                notes.append(
                    f"the {mode} fit was unsafe and was dropped; used the "
                    f"{attempt} fit")
            break
        notes.append(f"the {attempt} fit is unsafe: {'; '.join(faults)}")
        if chosen is None or similarity > chosen[1]:
            chosen = record

    correction, similarity, iterations, clipping, faults, solve_notes = chosen
    notes.extend(solve_notes)
    if similarity + 1e-6 < baseline:
        notes.append(
            f"tuning did not beat the untouched frame "
            f"({similarity * 100:.1f}% vs {baseline * 100:.1f}%)")
    passed = bool(similarity >= target and not faults)
    return TuningResult(correction, similarity, baseline, iterations, clipping,
                        notes, passed)
