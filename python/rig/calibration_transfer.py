#!/usr/bin/env python3
"""Derive one grid mode's workspace map from the other's - no camera, no rig.

The two grid modes (``vertical``, ``horizontal``) are photographed by the same
camera through the same lens, and the four corners of
``config/workspace_map.json`` describe the holder-travel envelope - machine
(0,0) out to the software cap - which does NOT change when the block is laid
down instead of standing up. Only the lattice *inside* that envelope changes,
and that lattice is read from ``config/rig.json``, not from the map.

So a calibrated ``vertical`` map already contains everything a ``horizontal``
map's four corners need: the same four image points. :func:`transfer_workspace_map`
copies them into the target mode's entry and pairs them with that mode's
geometry via ``MachineGrid.from_config(mode=...)`` - which carries horizontal's
``+1.9 cm`` pickup-cell registration (``trim_{x,y}_cm``), its ``3x10`` counts and
its ``blocked_cells`` list.

What this does NOT do is measure the target mode. A real placed-block run on the
target grid would also fold in whatever its firmware motion compensations
(``tool_offsets.cw``, ``BUILD_PLACEMENT_OFFSET_*``, ``SKEW_*``) fail to cancel.
This route assumes those land a block on the ideal lattice, which is what they
are tuned to do. **The transferred map is exactly as accurate as the source
map**; it is a drawing / target-selection aid, not an independent measurement of
target-mode placement.

See ``docs/STUDIO.md`` for the operator-facing note and ``AGENTS.md`` sections
3a / 3d-bis for why the motion knobs deliberately stay out of the drawn model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rig.config import GRID_MODES, load as load_rig_config
from rig.grid import MachineGrid
from rig.workspace import WORKSPACE_MAP_PATH, WorkspaceMap


class CalibrationTransferError(RuntimeError):
    """The source map cannot be reused for the requested target mode."""


@dataclass(frozen=True)
class TransferReport:
    """What :func:`transfer_workspace_map` did, for a UI or a CLI to print."""

    source_mode: str
    target_mode: str
    corners_normalized: list
    projection: dict | None
    target_cols: int
    target_rows: int
    path: Path
    saved: bool

    def describe(self) -> str:
        wrote = (f"-> {self.path.name}" if self.saved
                 else f"(dry run, {self.path.name} unchanged)")
        return (
            f"CALIBRATION DERIVED: {self.target_mode} grid "
            f"({self.target_cols}x{self.target_rows}) from the "
            f"{self.source_mode} calibration {wrote}. The four holder-envelope "
            f"corners are shared between the two modes; {self.target_mode}'s "
            f"lattice (including its registration trim) comes from "
            f"config/rig.json. This is a drawing aid derived from the "
            f"{self.source_mode} map, not a measured {self.target_mode} "
            f"calibration. Reload it in the app: press L in rig_build_v1, or "
            f"POST /api/calibration/reload in the web console"
        )


def transfer_workspace_map(source_mode: str = "vertical",
                           target_mode: str = "horizontal", *,
                           path: Path | str = WORKSPACE_MAP_PATH,
                           cfg: dict | None = None,
                           save: bool = True) -> tuple[WorkspaceMap, TransferReport]:
    """Build ``target_mode``'s workspace-map entry from ``source_mode``'s.

    Reads ``path``'s ``source_mode`` entry, keeps its four normalized corners
    and its ``projection``, and writes a ``target_mode`` entry pairing them with
    ``MachineGrid.from_config(mode=target_mode)``. The other mode's entry is
    left untouched. Returns ``(map, report)``; raises
    :class:`CalibrationTransferError` with a sentence an operator can act on.
    """
    path = Path(path)
    for label, value in (("source", source_mode), ("target", target_mode)):
        if value not in GRID_MODES:
            raise CalibrationTransferError(
                f"{label} mode must be one of {', '.join(GRID_MODES)}, "
                f"not {value!r}")
    if source_mode == target_mode:
        raise CalibrationTransferError(
            f"source and target are both {source_mode!r}; there is nothing to "
            f"derive - run a real calibration for that mode instead")
    if not path.exists():
        raise CalibrationTransferError(
            f"{path} does not exist; calibrate the {source_mode} grid first "
            f"(BLOCK CALIBRATION -> BLOCK CAL SAVE, or camera/block_grid_calibrate.py)")

    try:
        source = WorkspaceMap.load(path, mode=source_mode)
    except (OSError, ValueError, KeyError) as exc:
        raise CalibrationTransferError(
            f"cannot read the {source_mode} calibration from {path.name}: "
            f"{exc}") from exc

    if source.projection is None:
        raise CalibrationTransferError(
            f"the {source_mode} calibration carries no projection identity, so "
            f"a map derived from it would be written and then silently ignored "
            f"by every consumer. Re-save the {source_mode} calibration with a "
            f"real projection first")

    source_grid = source.mapped_grid
    if source_grid is None or not source_grid.has_physical_scale:
        raise CalibrationTransferError(
            f"the {source_mode} calibration carries no physical grid geometry "
            f"(pre-gap map format); recalibrate that mode before deriving from it")

    cfg = cfg if cfg is not None else load_rig_config(reload=True)
    target_grid = MachineGrid.from_config(cfg, mode=target_mode)

    if (source_grid.workspace_width_cm != target_grid.workspace_width_cm
            or source_grid.workspace_height_cm != target_grid.workspace_height_cm):
        raise CalibrationTransferError(
            f"the holder-travel envelope differs between the {source_mode} map "
            f"({source_grid.workspace_width_cm:g}x"
            f"{source_grid.workspace_height_cm:g} cm) and the {target_mode} "
            f"config ({target_grid.workspace_width_cm:g}x"
            f"{target_grid.workspace_height_cm:g} cm). The four corners are only "
            f"shareable when it does not - the envelope describes the machine, "
            f"not the mode")

    derived = WorkspaceMap.from_grid_normalized(
        target_grid, source.corners, source.projection)
    if save:
        derived.save(path)

    report = TransferReport(
        source_mode=source_mode,
        target_mode=target_mode,
        corners_normalized=[list(pair) for pair in derived.corners],
        projection=derived.projection,
        target_cols=target_grid.cols,
        target_rows=target_grid.rows,
        path=path,
        saved=bool(save),
    )
    return derived, report
