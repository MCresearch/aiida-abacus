# Bugs Found In `aiida-abacus`

This file records bugs and implementation gaps identified by comparing:

- the ABACUS source tree at `/home/bonan/appdir/abacus-develop`
- the current `aiida-abacus` parser, retrieval logic, and workflow handlers

The focus is on output files, warning/error handling, and critical physical quantities.

## Status Update

Updated on 2026-04-09 for the current branch:

- Addressed: 1, 2, 4, 5, 7, 8
- Partially addressed: 3
- Still open: 6, 9, 10

## 1. Trajectory stress arrays are never attached

**Severity:** High

**Problem**

The raw parser stores stress history under `all_stress`, but trajectory assembly looks for `all_stresses`.

- In `AbacusRawParser.parse_blocks()`, the key written is `all_stress`.
- In `compose_trajectory()`, the code checks `data_dict.get("all_stresses")`.

As a result, parsed stress trajectories are silently dropped from the `TrajectoryData` node.

**Evidence**

- `src/aiida_abacus/parsers/raw_parsers.py`
  - `self.results["all_stress"] = all_stress`
- `src/aiida_abacus/parsers/abacus.py`
  - `if data_dict.get("all_stresses"):`

**Impact**

- Relaxation and MD calculations lose stress trajectory data in AiiDA outputs.
- This is especially problematic for variable-cell relaxations where stress is a critical physical quantity.

**Suggested fix**

Use one canonical key consistently, preferably `all_stress` everywhere, or support both during a transition.

## 2. Default-retrieved `istate.info` is not parsed or used

**Severity:** Medium

**Problem**

`istate.info` is included in the default retrieve list, but `AbacusParser` never reads it.

Instead, the optional `bands` output is reconstructed from eigenvalue and k-point sections embedded in `running_*.log`.

**Evidence**

- `src/aiida_abacus/common/__init__.py`
  - `DEFAULT_RETRIEVE_FILES = ("INPUT", "kpoints", "device.log", "warning.log", "istate.info", ...)`
- `src/aiida_abacus/parsers/abacus.py`
  - `bands` are built from `raw_parser.parse_eigenvalues()` and `raw_parser.parse_kpoints()`
  - no parsing path exists for `istate.info`

**Impact**

- Retrieval cost without parser value.
- Missed opportunity to use the dedicated ABACUS eigenvalue/occupation output file.
- Increased dependence on `running_*.log` formatting.

**Suggested fix**

Either:

- parse `istate.info` and use it as the preferred source for eigenvalues/occupations, or
- remove it from the default retrieve list.

## 3. Retrieved `abacus_output` is ignored by the parser

**Severity:** Low

**Problem**

The calcjob always retrieves `abacus_output`, and the parser adds it to `expected_files`, but no parser logic uses it.

**Evidence**

- `src/aiida_abacus/calculations.py`
  - `spec.inputs["metadata"]["options"]["output_filename"].default = cls._ABACUS_OUTPUT`
  - retrieve list includes `[self._ABACUS_OUTPUT, ".", 0]`
- `src/aiida_abacus/parsers/abacus.py`
  - `expected_files.append(AbacusCalculation._ABACUS_OUTPUT)`
  - no later read of that file

**Impact**

- Unnecessary retrieval and clutter.
- Confusing maintenance signal because it appears semantically important but is unused.

**Suggested fix**

Either remove it from expected parsing inputs or define a clear purpose for consuming it.

## 4. Missing output files do not trigger the declared missing-files exit code

**Severity:** Medium

**Problem**

The parser records missing expected files only as a logger warning. It never returns `ERROR_MISSING_OUTPUT_FILES`, even though that exit code is declared.

**Evidence**

- `src/aiida_abacus/parsers/abacus.py`
  - missing files are appended to `missing`
  - only `self.logger.warning(...)` is called
- `src/aiida_abacus/calculations.py`
  - exit code `300 ERROR_MISSING_OUTPUT_FILES` is defined

**Impact**

- Silent partial retrieval can pass through parsing.
- Downstream outputs may be incomplete with no structured failure status.

**Suggested fix**

Define which files are truly mandatory by calculation type and return `ERROR_MISSING_OUTPUT_FILES` when any mandatory file is absent.

## 5. Warning handling relies only on `warning.log`, not `running_*.log`

**Severity:** Medium

**Problem**

The parser exposes warnings only from `warning.log`. It does not scan `running_*.log` for `Notice:` or other warning-like patterns, even though some important warnings appear there.

For example, ABACUS logs lines like:

- `Notice: Threshold on eigenvalues was too large.`

The current implementation only captures such warnings if they are duplicated into `warning.log`.

**Evidence**

- `src/aiida_abacus/parsers/abacus.py`
  - warnings come only from `WarningLogParser`
- `src/aiida_abacus/parsers/raw_parsers.py`
  - `parse_notifications()` only checks convergence markers, not generic warnings

**Impact**

- Important numerical-quality warnings may be lost.
- Warning coverage depends on ABACUS duplication behavior rather than robust parsing.

**Suggested fix**

Add warning-pattern parsing from `running_*.log` and merge with `warning.log` notifications.

## 6. `bands` parsing depends on `running_*.log` formatting and head-rank k-point reporting

**Severity:** Medium

**Problem**

Optional `bands` output is parsed from the running log using regexes and assumes complete k-point/eigenvalue information is present there.

The raw parser itself notes that ABACUS reports k-points only on the head MPI process.

**Evidence**

- `src/aiida_abacus/parsers/raw_parsers.py`
  - comment: `Abacus only report the kpoint on the head MPI process!`
- `src/aiida_abacus/parsers/abacus.py`
  - `assert kcoord.shape[0] == eigenvalues.shape[1], "Inconsistent number of kpoints reported (do not use kpar)"`

**Impact**

- Fragile parsing for parallel calculations.
- `bands` output may fail or be unusable under some MPI/k-point layouts.

**Suggested fix**

Prefer dedicated ABACUS output files for bands/eigenvalues where available, and reduce reliance on log scraping.

## 7. The parser detects `geometry_not_converged` and `relax_scf_not_converged` but does not act on them

**Severity:** Medium

**Problem**

`parse_notifications()` recognizes:

- `geometry_not_converged`
- `relax_scf_not_converged`

But `AbacusParser.parse()` only acts on:

- `scf_not_converged`
- `ionic_not_converged`

The additional notification classes are effectively ignored.

**Evidence**

- `src/aiida_abacus/parsers/raw_parsers.py`
  - patterns include `geometry_not_converged` and `relax_scf_not_converged`
- `src/aiida_abacus/parsers/abacus.py`
  - only checks `scf_not_converged` and `ionic_not_converged`

**Impact**

- Some semantically distinct failure states are detected but not surfaced as parser exit codes.
- This can blur the difference between ionic convergence issues and mixed final-state issues.

**Suggested fix**

Either:

- add dedicated exit-code handling, or
- remove dead notification categories if they are intentionally unsupported.

## 8. `device.log` is retrieved by default but not parsed

**Severity:** Low

**Problem**

`device.log` is in the default retrieve list, but the parser does nothing with it.

**Evidence**

- `src/aiida_abacus/common/__init__.py`
  - `device.log` is part of `DEFAULT_RETRIEVE_FILES`
- No parser code references `device.log`

**Impact**

- Extra retrieval overhead.
- Potentially useful hardware/runtime diagnostics are ignored.

**Suggested fix**

Either parse and expose it, or remove it from default retrieval.

## 9. Most physically important ABACUS output files are not mapped into AiiDA outputs

**Severity:** Medium

**Problem**

ABACUS can generate many physically important outputs, but the plugin currently does not parse them:

- DOS / PDOS
- Mulliken analysis
- charge density cubes
- potential cubes
- ELF
- partial charge and wavefunction cubes
- H/S/DM/R-space matrix outputs
- Fermi surface output

This is not a crash bug, but it is a functional coverage gap relative to ABACUS capabilities.

**Evidence**

- ABACUS output controls are defined in:
  - `source/source_io/module_parameter/read_input_item_output.cpp`
- `aiida-abacus` parser only exposes:
  - `misc`
  - optional `bands`
  - optional `internal_parameters`
  - optional `kpoints`
  - `structure` / `trajectory` for relax/md

**Impact**

- Important physical quantities remain inaccessible from standard AiiDA outputs.
- Users must manually inspect retrieved files for key analyses.

**Suggested fix**

Prioritize parsers for:

1. DOS / PDOS
2. Mulliken
3. charge and potential cubes metadata
4. matrix outputs when requested

## 10. Workflow recovery logic ignores warning-level numerical pathologies

**Severity:** Medium

**Problem**

The base workchain only reacts to:

- incomplete runs
- electronic non-convergence
- ionic non-convergence

It does not react to warning-level issues such as repeated large eigenvalue-threshold warnings.

**Evidence**

- `src/aiida_abacus/workflows/base.py`
  - handlers exist only for incomplete, electronic, and ionic failures

**Impact**

- Numerically questionable runs can be treated as fully acceptable if they converge formally.
- No adaptive response to known quality warnings.

**Suggested fix**

Promote selected warnings into workflow-level checks, at minimum configurable policy checks.

## Recommended Priority Order

1. Fix trajectory stress attachment bug.
2. Decide mandatory retrieved files and enforce `ERROR_MISSING_OUTPUT_FILES`.
3. Improve warning extraction from `running_*.log`.
4. Decide whether `istate.info`, `device.log`, and `abacus_output` should be parsed or no longer retrieved by default.
5. Add parsers for higher-value physical outputs such as DOS/PDOS and Mulliken analysis.
