"""
Input generators based on protocols.

This module provides protocol-backed builder generators for the public ABACUS
workchains. The implementation follows the same general idea as
``aiida-vasp``: users start from a preset and protocol, build a workchain
builder, and then mutate the generated inputs through a small convenience API.
"""

from __future__ import annotations

import warnings
from copy import deepcopy
from dataclasses import dataclass, field, fields
from itertools import chain
from pathlib import Path
from typing import Any

from aiida import orm
from aiida.engine import run_get_node, submit
from aiida.engine.processes.builder import ProcessBuilderNamespace
from aiida.plugins import WorkflowFactory
from yaml import safe_load

from aiida_abacus.common import recursive_merge

__all__ = [
    "AbacusBandInputGenerator",
    "AbacusBaseInputGenerator",
    "AbacusInputGenerator",
    "AbacusRelaxInputGenerator",
    "BaseInputGenerator",
    "PresetConfig",
    "get_library_path",
    "get_preset_library_paths",
    "list_protocol_presets",
]


def get_library_path() -> Path:
    """Return the package directory that stores preset YAML files."""

    return Path(__file__).parent / "presets"


def get_preset_library_paths() -> tuple[Path, ...]:
    """Return the directories searched for preset definitions."""

    return (
        get_library_path(),
        Path("~/.aiida-abacus/presets").expanduser(),
        Path("~/.aiida-abacus/protocol_presets").expanduser(),
    )


def _iter_preset_candidate_paths(fname: str):
    """Yield candidate paths for a preset name."""

    preset_path = Path(fname)
    if preset_path.suffix in {".yaml", ".yml"}:
        yield preset_path.expanduser()
        return

    for parent in get_preset_library_paths():
        yield parent / f"{fname}.yaml"
        yield parent / f"{fname}.yml"


def list_protocol_presets() -> list[Path]:
    """List all available preset files."""

    presets = []
    seen = set()

    for parent in get_preset_library_paths():
        files = chain(parent.glob("*.yaml"), parent.glob("*.yml"))
        for file in files:
            resolved = file.absolute()
            if resolved in seen:
                continue
            seen.add(resolved)
            presets.append(resolved)

    return presets


@dataclass
class PresetConfig:
    """Preset-backed defaults used by :class:`BaseInputGenerator`."""

    name: str
    default_protocol: str
    default_code: str
    code_specific: dict = field(default_factory=dict)
    default_options: dict = field(default_factory=dict)
    default_settings: dict = field(default_factory=dict)
    protocol_overrides: dict = field(default_factory=dict)
    default_relax_settings: dict = field(default_factory=dict)
    default_band_settings: dict = field(default_factory=dict)

    @classmethod
    def from_file(cls, fname: str) -> PresetConfig:
        """Load a preset definition from the package or user preset search path."""

        target_path = next((path for path in _iter_preset_candidate_paths(fname) if path.is_file()), None)
        if target_path is None:
            available = [p.stem for p in list_protocol_presets()]
            raise RuntimeError(f"Cannot find preset definition for '{fname}'. Available presets: {available}")

        with open(target_path, encoding="utf-8", mode="r") as fhandle:
            data = safe_load(fhandle) or {}

        valid_fields = {f.name for f in fields(cls)}
        unknown = set(data) - valid_fields
        if unknown:
            raise ValueError(f"Unknown keys in preset '{fname}': {unknown}. Valid keys: {sorted(valid_fields)}")

        return cls(**data)

    def get_code_specific_options(self, code: str, namespace: str) -> dict[str, Any]:
        """Return preset-backed configuration for a given code and namespace."""

        if code in self.code_specific and namespace in self.code_specific[code]:
            code_specific = self.code_specific[code][namespace]
            default = getattr(self, f"default_{namespace}", {}) or {}
            return recursive_merge(default, code_specific)

        return deepcopy(getattr(self, f"default_{namespace}", {}) or {})

    def resolve_code_specific_configuration(self, code: str) -> dict[str, dict[str, Any]]:
        """Resolve all preset-derived fragments for a given code label."""

        return {
            "options": self.get_code_specific_options(code, "options"),
            "settings": self.get_code_specific_options(code, "settings"),
            "parameters": self.get_code_specific_options(code, "parameters"),
        }


def join_namespace_path(parent: str, child: str) -> str:
    """Join two ``.``-separated builder paths."""

    if not parent:
        return child
    if not child:
        return parent
    return f"{parent}.{child}"


class BaseInputGenerator:
    """
    Base class for protocol-backed builder generators.

    The generator serves two purposes:
    - build a workchain builder from a preset, protocol and structure
    - provide light convenience mutators for common builder ports
    """

    WF_ENTRYPOINT = "abacus.base"
    WORKFLOW_LABEL = "ABACUS workflow"
    WORKFLOW_SUMMARY = "Protocol-based ABACUS builder generator."

    def __init__(
        self,
        preset_name: str = "default",
        protocol: str | None = None,
        verbose: bool = False,
    ) -> None:
        assert hasattr(self, "WF_ENTRYPOINT"), "WF_ENTRYPOINT must be specified by the class"
        self.verbose = verbose
        self.preset_name = preset_name
        self.preset = PresetConfig.from_file(preset_name)
        self.protocol = protocol if protocol is not None else self.preset.default_protocol
        self.builder = None

    @staticmethod
    def _load_code_node(code):
        """Return a stored code node from a label/PK or pass through an existing code node."""

        if isinstance(code, orm.AbstractCode):
            if not code.is_stored:
                raise ValueError("The supplied code node must be stored before it can be used to build inputs.")
            return code

        return orm.load_code(code)

    @staticmethod
    def _get_code_identifier(code) -> str:
        """Return a stable label used for preset lookup."""

        if isinstance(code, orm.AbstractCode):
            return code.full_label
        return str(code)

    def _resolve_build_request(self, *, code=None, protocol=None, overrides=None, options=None) -> dict[str, Any]:
        """Resolve preset-backed defaults before constructing a workflow builder."""

        resolved_code = code or self.preset.default_code
        resolved_protocol = self.protocol if protocol is None else protocol
        profile_config = self.preset.resolve_code_specific_configuration(self._get_code_identifier(resolved_code))
        resolved_overrides = recursive_merge(self.preset.protocol_overrides, overrides or {})
        resolved_options = recursive_merge(profile_config["options"], options or {})

        return {
            "code": resolved_code,
            "protocol": resolved_protocol,
            "overrides": resolved_overrides,
            "options": resolved_options,
            "profile_config": profile_config,
        }

    def _finalize_builder(self, builder, *, profile_config: dict[str, dict[str, Any]]):
        """Store the builder and apply preset/profile defaults consistently."""

        self.builder = builder
        self.set_settings(profile_config["settings"])
        # Merge code-specific parameters into the ``input`` sub-dict of each parameter port.
        # Only the ``input`` namespace is extracted; other ABACUS parameter namespaces
        # (e.g. ``stru``) are not set via presets and should be configured directly.
        params_from_preset = profile_config.get("parameters", {})
        if params_from_preset:
            input_updates = params_from_preset.get("input", {})
            if input_updates:
                self.set_input(input_updates)
        return builder

    def build(self, structure, code=None, protocol=None, overrides=None, **kwargs):
        """Build and store a workflow builder from the configured preset and protocol."""

        build_request = self._resolve_build_request(
            code=code,
            protocol=protocol,
            overrides=overrides,
            options=kwargs.pop("options", {}),
        )

        builder = WorkflowFactory(self.WF_ENTRYPOINT).get_builder_from_protocol(
            code=self._load_code_node(build_request["code"]),
            structure=structure,
            protocol=build_request["protocol"],
            overrides=build_request["overrides"],
            options=build_request["options"],
            **kwargs,
        )

        return self._finalize_builder(builder, profile_config=build_request["profile_config"])

    def get_builder(self, structure, code=None, protocol=None, overrides=None, **kwargs):
        """Compatibility alias for :meth:`build`."""

        return self.build(structure=structure, code=code, protocol=protocol, overrides=overrides, **kwargs)

    def _require_builder(self):
        """Raise if the generator has not built a builder yet."""

        if self.builder is None:
            raise AttributeError("Builder has not been initialized. Call `build(...)` first.")

    def _resolve_namespace(self, namespace_path: str | None = None):
        """Resolve a builder namespace by ``.`` separated path."""

        self._require_builder()

        if not namespace_path:
            return self.builder

        item = self.builder
        for part in namespace_path.split("."):
            item = item.get(part)
            if item is None:
                raise AttributeError(f"Namespace `{namespace_path}` is not available on this builder.")

        return item

    def _resolve_parent_and_leaf(self, port_path: str):
        """Resolve the parent namespace and leaf name for a ``.`` separated path."""

        if not port_path:
            raise ValueError("A non-empty port path is required.")

        parts = port_path.split(".")
        parent = self._resolve_namespace(".".join(parts[:-1])) if len(parts) > 1 else self.builder
        return parent, parts[-1]

    def _get_path_value(self, port_path: str):
        """Return the value stored at ``port_path``."""

        parent, leaf = self._resolve_parent_and_leaf(port_path)
        return parent.get(leaf)

    def _path_exists(self, port_path: str) -> bool:
        """Return whether ``port_path`` resolves on the current builder."""

        try:
            self._resolve_parent_and_leaf(port_path)
        except (AttributeError, KeyError, ValueError):
            return False

        return True

    def _set_path_value(self, port_path: str, value) -> None:
        """Set the value stored at ``port_path``."""

        parent, leaf = self._resolve_parent_and_leaf(port_path)
        setattr(parent, leaf, value)

    @property
    def reference_structure(self):
        """Return the most relevant structure node currently attached to the builder."""

        for port_path in (
            "structure",
            "abacus.structure",
            "base.abacus.structure",
            "relax.structure",
            "relax.base.abacus.structure",
        ):
            if self.builder is not None and self._path_exists(port_path):
                structure = self._get_path_value(port_path)
                if structure is not None:
                    return structure

        return None

    def clone(self):
        """Return a clone of the generator bound to a deep-copied builder."""

        cloned = self.__class__(preset_name=self.preset_name, protocol=self.protocol, verbose=self.verbose)
        cloned.builder = deepcopy(self.builder)
        return cloned

    def set_input(self, input_updates=None, update_all=True, ports=None, **kwargs):
        """Update the ``input`` namespace inside parameter dictionaries."""

        updates = deepcopy(input_updates or {})
        updates.update(kwargs)
        if not updates:
            return self

        self._require_builder()

        if update_all:
            ports_nodes = recursive_search_dict_with_key(self.builder, "input")
        else:
            ports = ports or ["parameters"]
            ports_nodes = [[port, self._get_port_node(port)] for port in ports]

        for port, node in ports_nodes:
            self._update_dict_node(port, updates, dict_node=node, namespace="input")

        return self

    def set_options(self, option_updates=None, ports=None, update_all=True, **kwargs):
        """Update ``metadata.options`` for one or more calculation namespaces."""

        updates = recursive_merge(option_updates or {}, kwargs)
        if not updates:
            return self

        self._require_builder()

        if update_all:
            calc_namespaces = []
            for port, namespace in recursive_search_port_basename(self.builder, "abacus"):
                if "metadata" in namespace and "options" in namespace["metadata"]:
                    calc_namespaces.append([port, namespace])
        else:
            ports = ports or ["abacus"]
            calc_namespaces = [[port, self._get_port_node(port)] for port in ports]

        for port, namespace in calc_namespaces:
            if has_content(namespace) or namespace._port_namespace._required:
                namespace["metadata"]["options"] = recursive_merge(dict(namespace["metadata"]["options"]), updates)
            elif self.verbose:
                warnings.warn(f"set_options: skipping optional namespace '{port}' with no content.", stacklevel=2)

        return self

    def set_resources(self, resources_updates=None, ports=None, update_all=True, **kwargs):
        """Update ``metadata.options.resources`` for one or more calculation namespaces."""

        updates = deepcopy(resources_updates or {})
        updates.update(kwargs)
        if not updates:
            return self

        self._require_builder()

        if update_all:
            calc_namespaces = []
            for port, namespace in recursive_search_port_basename(self.builder, "abacus"):
                if "metadata" in namespace and "options" in namespace["metadata"]:
                    calc_namespaces.append([port, namespace])
        else:
            ports = ports or ["abacus"]
            calc_namespaces = [[port, self._get_port_node(port)] for port in ports]

        for port, namespace in calc_namespaces:
            if has_content(namespace) or namespace._port_namespace._required:
                options = namespace["metadata"]["options"]
                options.setdefault("resources", {})
                options["resources"] = recursive_merge(options["resources"], updates)
            elif self.verbose:
                warnings.warn(f"set_resources: skipping optional namespace '{port}' with no content.", stacklevel=2)

        return self

    def _update_ports_by_base_name(
        self, value, port_basename, ports=None, update_all=True, merge=False, skip_empty=True
    ):
        """Update builder ports by their basename."""

        _ = skip_empty
        self._require_builder()

        if update_all:
            port_and_nodes = recursive_search_port_basename(self.builder, port_basename)
        else:
            ports = ports or [port_basename]
            port_and_nodes = [[port, self._get_port_node(port)] for port in ports]

        for port, node in port_and_nodes:
            if merge and isinstance(node, orm.Dict):
                self._set_node_to_port(port, update_dict_node(node, value))
            else:
                self._set_node_to_port(port, value)

        return self

    def _update_dict_node(self, port, update: dict, dict_node=None, namespace=None, reuse_if_possible=True):
        """Update a ``Dict`` node at ``port`` with a merged mapping."""

        if not update:
            return

        dict_node = dict_node or self._get_port_node(port)
        updated = update_dict_node(dict_node, update, namespace=namespace, reuse_if_possible=reuse_if_possible)
        self._set_node_to_port(port, updated)

    def _set_generic_port_by_dict(self, _port_name, value=None, ports=None, update_all=True, skip_empty=True, **kwargs):
        """Merge a mapping into one or more generic ``Dict`` ports."""

        if value is None and not kwargs:
            return self

        value = deepcopy(value or {})
        value.update(kwargs)

        return self._update_ports_by_base_name(
            value, _port_name, ports=ports, update_all=update_all, skip_empty=skip_empty, merge=True
        )

    def _get_port_node(self, port):
        """Return the value stored at a specific builder path."""

        parts = port.split(".")
        item = self.builder
        for part in parts:
            item = item.get(part)
        return item

    def _set_node_to_port(self, port, node: orm.Data):
        """Set a node at a specific builder path."""

        if node is None:
            return

        parts = port.split(".")
        item = self.builder
        for part in parts[:-1]:
            item = item[part]
        setattr(item, parts[-1], node)

    def __repr__(self):
        string = f"{self.__class__.__name__}(protocol={self.protocol}, preset_name={self.preset_name})"
        if self.builder is not None:
            string += f"\nBuilder: {self.builder}"
        return string

    def _repr_pretty_(self, p, _=None) -> str:
        """Pretty representation for IPython consoles and notebooks."""

        string = f"{self.__class__.__name__}(protocol={self.protocol}, preset_name={self.preset_name})"
        p.text(string)
        if self.builder is not None:
            p.text("\nWith Builder:\n")
            self.builder._repr_pretty_(p, _)

    def set_kpoints_distance(self, value, ports=None, update_all=True):
        """Update ``kpoints_distance`` ports."""

        self._update_ports_by_base_name(orm.Float(value), "kpoints_distance", ports=ports, update_all=update_all)
        return self

    def set_kpoints_mesh(self, mesh: list[int], offset=(0.0, 0.0, 0.0), ports=None, update_all=True):
        """Set explicit mesh-based k-points using the reference structure cell."""

        self._require_builder()

        structure = self.reference_structure
        if structure is None:
            warnings.warn(
                "set_kpoints_mesh: no reference structure found on the builder; k-points were not set.", stacklevel=2
            )
            return self

        kpoints = orm.KpointsData()
        kpoints.set_cell_from_structure(structure)
        kpoints.set_kpoints_mesh(mesh, list(offset))
        self._update_ports_by_base_name(kpoints, "kpoints", ports=ports, update_all=update_all)

        return self

    def set_label(self, label=None):
        """Set ``builder.metadata.label``."""

        self._require_builder()
        label = label or (self.reference_structure.label if self.reference_structure else None)
        self.builder.metadata.label = label
        return self

    def set_pseudo_family(self, value, ports=None, update_all=True):
        """Update pseudo family ports."""

        self._update_ports_by_base_name(orm.Str(value), "pseudo_family", ports=ports, update_all=update_all)
        return self

    def set_code(self, value, ports=None, update_all=True):
        """Update code ports."""

        if not isinstance(value, orm.AbstractCode):
            value = orm.load_code(value)
        self._update_ports_by_base_name(value, "code", ports=ports, update_all=update_all)
        return self

    def set_settings(self, value, ports=None, update_all=True, **kwargs):
        """Update ``settings`` ports."""

        return self._set_generic_port_by_dict("settings", value=value, ports=ports, update_all=update_all, **kwargs)

    def submit(self) -> orm.WorkChainNode:
        """Submit the current builder to the daemon."""

        self._require_builder()
        return submit(self.builder)

    def run_get_node(self, verbose: bool = False):
        """Run the current builder in-process and return the ``run_get_node`` result."""

        self._require_builder()
        output = run_get_node(self.builder)

        if not output.node.is_finished_ok and verbose:
            for node in output.node.called_descendants:
                if isinstance(node, orm.CalcJobNode):
                    try:
                        stdout = node.outputs.retrieved.get_object_content("abacus_output")
                        print(node, "STDOUT:", stdout)
                        print(node, "Retrieved files:", node.outputs.retrieved.list_object_names())
                    except Exception:
                        pass
                    print(node, "Exit_message", node.exit_message)

        return output


def update_dict_node(
    node: orm.Dict | None,
    content: dict[str, Any],
    namespace: str | None = None,
    reuse_if_possible: bool = True,
) -> orm.Dict:
    """Update an ``orm.Dict`` node with merged content.  If *node* is ``None``, a fresh ``orm.Dict`` is created."""

    if node is None:
        dtmp = {namespace: {}} if namespace else {}
    else:
        dtmp = node.get_dict()
    dtmp_backup = None
    if node is not None and reuse_if_possible and node.is_stored:
        dtmp_backup = deepcopy(dtmp)

    left = dtmp.get(namespace, {}) if namespace else dtmp
    left = recursive_merge(left, content)

    if namespace:
        dtmp[namespace] = left
    else:
        dtmp = left

    if node is None:
        return orm.Dict(dict=dtmp)

    if node.is_stored:
        if reuse_if_possible and dtmp == dtmp_backup:
            return node
        return orm.Dict(dict=dtmp)

    node.set_dict(dtmp)
    return node


def recursive_search_dict_with_key(namespace, search_key):
    """Recursively search for ``Dict`` nodes that contain ``search_key``."""

    ports = []
    for port_key in namespace._valid_fields:
        value = namespace.get(port_key)
        if isinstance(value, orm.Dict) and search_key in value.get_dict():
            ports.append([port_key, value])
        if isinstance(value, ProcessBuilderNamespace):
            ports.extend(
                [
                    [f"{port_key}.{sub_key}", sub_value]
                    for sub_key, sub_value in recursive_search_dict_with_key(value, search_key)
                ]
            )
    return ports


def recursive_search_port_basename(namespace, basename):
    """Recursively search for builder ports with a matching basename."""

    ports = []
    for port_key in namespace._valid_fields:
        value = namespace.get(port_key)
        if port_key == basename:
            ports.append([port_key, value])
        if isinstance(value, ProcessBuilderNamespace):
            ports.extend(
                [
                    [f"{port_key}.{sub_key}", sub_value]
                    for sub_key, sub_value in recursive_search_port_basename(value, basename)
                ]
            )
    return ports


def has_content(mapping):
    """Return whether a nested mapping contains at least one non-empty value."""

    for _key, value in mapping.items():
        if hasattr(value, "items"):
            if has_content(value):
                return True
        else:
            return True
    return False


class CalculationNamespaceGenerator:
    """Convenience mutators for an ABACUS calculation namespace."""

    def __init__(self, root: BaseInputGenerator, namespace_path: str) -> None:
        self.root = root
        self.namespace_path = namespace_path

    @property
    def builder(self):
        """Return the resolved calculation namespace."""

        return self.root._resolve_namespace(self.namespace_path)

    @property
    def reference_structure(self):
        """Return the structure attached to this calculation branch."""

        structure_path = join_namespace_path(self.namespace_path, "structure")
        if self.root._path_exists(structure_path):
            return self.root._get_path_value(structure_path)
        return None

    def _port(self, leaf: str) -> str:
        return join_namespace_path(self.namespace_path, leaf)

    def set_input(self, input_updates=None, **kwargs):
        """Update ``parameters.input`` for this calculation branch."""

        self.root.set_input(input_updates, ports=[self._port("parameters")], update_all=False, **kwargs)
        return self

    def set_settings(self, value=None, **kwargs):
        """Update the calculation ``settings`` port."""

        self.root.set_settings(value, ports=[self._port("settings")], update_all=False, **kwargs)
        return self

    def set_options(self, value=None, **kwargs):
        """Update ``metadata.options`` for this calculation branch."""

        self.root.set_options(value, ports=[self.namespace_path], update_all=False, **kwargs)
        return self

    def set_resources(self, value=None, **kwargs):
        """Update ``metadata.options.resources`` for this calculation branch."""

        self.root.set_resources(value, ports=[self.namespace_path], update_all=False, **kwargs)
        return self

    def set_code(self, value):
        """Update the calculation ``code`` port."""

        self.root.set_code(value, ports=[self._port("code")], update_all=False)
        return self

    def set_structure(self, structure):
        """Update the calculation ``structure`` port."""

        self.root._set_path_value(self._port("structure"), structure)
        return self

    def __repr__(self):
        return f"{self.__class__.__name__}(namespace_path={self.namespace_path!r})"


class WorkflowNamespaceGenerator:
    """Convenience mutators for a workflow branch that may expose an ``abacus`` child namespace."""

    def __init__(self, root: BaseInputGenerator, namespace_path: str = "") -> None:
        self.root = root
        self.namespace_path = namespace_path

    @property
    def builder(self):
        """Return the resolved workflow namespace."""

        return self.root._resolve_namespace(self.namespace_path)

    def _workflow_port(self, leaf: str) -> str:
        return join_namespace_path(self.namespace_path, leaf)

    def _calculation_namespace_path(self) -> str:
        namespace = self.builder
        if hasattr(namespace, "get") and namespace.get("abacus") is not None:
            return self._workflow_port("abacus")
        return self.namespace_path

    def abacus(self) -> CalculationNamespaceGenerator:
        """Return the underlying ABACUS calculation namespace for this workflow branch."""

        return CalculationNamespaceGenerator(self.root, self._calculation_namespace_path())

    def set_input(self, input_updates=None, **kwargs):
        """Update ``parameters.input`` on the child ABACUS namespace."""

        self.abacus().set_input(input_updates, **kwargs)
        return self

    def set_settings(self, value=None, **kwargs):
        """Update ``settings`` on the child ABACUS namespace."""

        self.abacus().set_settings(value, **kwargs)
        return self

    def set_options(self, value=None, **kwargs):
        """Update ``metadata.options`` on the child ABACUS namespace."""

        self.abacus().set_options(value, **kwargs)
        return self

    def set_resources(self, value=None, **kwargs):
        """Update ``metadata.options.resources`` on the child ABACUS namespace."""

        self.abacus().set_resources(value, **kwargs)
        return self

    def set_code(self, value):
        """Update the code on the child ABACUS namespace."""

        self.abacus().set_code(value)
        return self

    def set_pseudo_family(self, value):
        """Update the workflow-level ``pseudo_family`` port."""

        self.root._set_path_value(self._workflow_port("pseudo_family"), orm.Str(value))
        return self

    def set_kpoints_distance(self, value):
        """Update the workflow-level ``kpoints_distance`` port."""

        self.root._set_path_value(self._workflow_port("kpoints_distance"), orm.Float(value))
        return self

    def set_kpoints_mesh(self, mesh: list[int], offset=(0.0, 0.0, 0.0)):
        """Attach explicit mesh k-points to the workflow branch."""

        structure = self.abacus().reference_structure
        if structure is None:
            raise RuntimeError("No structure is attached to this namespace; cannot construct KpointsData.")

        kpoints = orm.KpointsData()
        kpoints.set_cell_from_structure(structure)
        kpoints.set_kpoints_mesh(mesh, list(offset))
        self.root._set_path_value(self._workflow_port("kpoints"), kpoints)
        return self

    def __repr__(self):
        return f"{self.__class__.__name__}(namespace_path={self.namespace_path!r})"


class RelaxSettingsGenerator:
    """Convenience mutator for ``relax_settings`` ports."""

    def __init__(self, root: BaseInputGenerator, namespace_path: str = "") -> None:
        self.root = root
        self.namespace_path = namespace_path

    def set_relax_settings(self, value=None, **kwargs):
        """Update a ``relax_settings`` port."""

        port = join_namespace_path(self.namespace_path, "relax_settings")
        self.root._set_generic_port_by_dict("relax_settings", ports=[port], update_all=False, value=value, **kwargs)
        return self

    def __repr__(self):
        return f"{self.__class__.__name__}(namespace_path={self.namespace_path!r})"


class BandSettingsGenerator:
    """Convenience mutator for ``band_settings`` and ``kpoints_band`` ports."""

    def __init__(self, root: BaseInputGenerator, namespace_path: str = "") -> None:
        self.root = root
        self.namespace_path = namespace_path

    def set_band_settings(self, value=None, **kwargs):
        """Update a ``band_settings`` port."""

        port = join_namespace_path(self.namespace_path, "band_settings")
        self.root._set_generic_port_by_dict("band_settings", ports=[port], update_all=False, value=value, **kwargs)
        return self

    def set_kpoints_band(self, kpoints):
        """Set explicit band-path k-points."""

        port = join_namespace_path(self.namespace_path, "kpoints_band")
        self.root._set_path_value(port, kpoints)
        return self

    def __repr__(self):
        return f"{self.__class__.__name__}(namespace_path={self.namespace_path!r})"


class AbacusInputGenerator(BaseInputGenerator):
    """Input generator for ``AbacusBaseWorkChain``."""

    WF_ENTRYPOINT = "abacus.base"
    WORKFLOW_LABEL = "Single ABACUS workchain"
    WORKFLOW_SUMMARY = "Configure one abacus.base workflow builder."

    def abacus(self) -> WorkflowNamespaceGenerator:
        """Return a wrapper for the base workflow namespace."""

        return WorkflowNamespaceGenerator(self, "")


class AbacusBaseInputGenerator(AbacusInputGenerator):
    """Backward-compatible alias of :class:`AbacusInputGenerator`."""


class AbacusRelaxInputGenerator(BaseInputGenerator):
    """Input generator for ``AbacusRelaxWorkChain``."""

    WF_ENTRYPOINT = "abacus.relax"
    WORKFLOW_LABEL = "Relaxation workchain"
    WORKFLOW_SUMMARY = "Configure a relaxation workflow with base, final-SCF and relax_settings branches."

    def base(self) -> WorkflowNamespaceGenerator:
        """Return the main ``base`` workflow branch."""

        return WorkflowNamespaceGenerator(self, "base")

    def abacus(self) -> WorkflowNamespaceGenerator:
        """Compatibility alias for the main relaxation branch."""

        return self.base()

    def final_scf(self) -> WorkflowNamespaceGenerator:
        """Return the optional ``base_final_scf`` branch."""

        return WorkflowNamespaceGenerator(self, "base_final_scf")

    def relax(self) -> RelaxSettingsGenerator:
        """Return a mutator for the top-level ``relax_settings`` port."""

        return RelaxSettingsGenerator(self, "")

    def set_relax_settings(self, value=None, **kwargs):
        """Update the top-level ``relax_settings`` port."""

        self.relax().set_relax_settings(value, **kwargs)
        return self

    def build(self, structure, code=None, protocol=None, overrides=None, **kwargs):
        """Build a relax workflow builder and apply preset relax settings."""

        builder = super().build(structure=structure, code=code, protocol=protocol, overrides=overrides, **kwargs)
        if self.preset.default_relax_settings:
            self.set_relax_settings(self.preset.default_relax_settings)
        return builder


class AbacusBandInputGenerator(BaseInputGenerator):
    """Input generator for ``AbacusBandWorkChain``."""

    WF_ENTRYPOINT = "abacus.band"
    WORKFLOW_LABEL = "Band-structure workchain"
    WORKFLOW_SUMMARY = "Configure SCF, optional relax, and band-path settings for abacus.band."

    def base(self) -> WorkflowNamespaceGenerator:
        """Return the SCF ``base`` branch."""

        return WorkflowNamespaceGenerator(self, "base")

    def scf(self) -> WorkflowNamespaceGenerator:
        """Compatibility alias for the SCF ``base`` branch."""

        return self.base()

    def relax(self) -> WorkflowNamespaceGenerator:
        """Return the optional nested relax branch."""

        return WorkflowNamespaceGenerator(self, "relax")

    def bands(self) -> BandSettingsGenerator:
        """Return a mutator for top-level band-path inputs."""

        return BandSettingsGenerator(self, "")

    def path(self) -> BandSettingsGenerator:
        """Compatibility alias for top-level band-path inputs."""

        return self.bands()

    def set_band_settings(self, value=None, **kwargs):
        """Update the top-level ``band_settings`` port."""

        self.bands().set_band_settings(value, **kwargs)
        return self

    def set_kpoints_band(self, kpoints):
        """Set explicit band-path k-points."""

        self.bands().set_kpoints_band(kpoints)
        return self

    def build(self, structure, code=None, protocol=None, overrides=None, **kwargs):
        """Build a band workflow builder and apply preset band settings."""

        builder = super().build(structure=structure, code=code, protocol=protocol, overrides=overrides, **kwargs)
        if self.preset.default_band_settings:
            self.set_band_settings(self.preset.default_band_settings)
        return builder
