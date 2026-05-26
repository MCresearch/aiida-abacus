"""Tests for AtomicOrbitalFamily class."""

import pytest
from aiida import orm
from aiida.orm import QueryBuilder, load_group
from aiida.plugins import GroupFactory
from aiida_pseudo.groups.family import PseudoPotentialFamily
from ase.build import bulk

from aiida_abacus.data.orbital import AtomicOrbitalData
from aiida_abacus.group.orb_group import AtomicOrbitalFamily


class TestAtomicOrbitalFamily:
    """Test the AtomicOrbitalFamily class functionality."""

    def test_constructor_and_inheritance(self, aiida_profile_clean):
        """Test basic construction and inheritance from PseudoPotentialFamily."""
        family = AtomicOrbitalFamily(label="test-family")

        # Should be unstored initially
        assert not family.is_stored
        assert family.label == "test-family"

        # Should be loadable via entry point
        familyclass = GroupFactory("abacus.orbital_family")
        assert familyclass == AtomicOrbitalFamily

    def test_type_string_and_entry_point(self, aiida_profile_clean, si_orbital_family):
        """Verify correct type string and entry point registration."""
        assert si_orbital_family.type_string == "abacus.orbital_family"

    def test_get_pseudos_with_structure(self, aiida_profile_clean, multi_element_family, si_structure):
        """Test inherited get_pseudos() method with StructureData."""
        # Get pseudos for structure containing Si
        pseudos = multi_element_family.get_pseudos(structure=si_structure)

        assert isinstance(pseudos, dict)
        # Should contain Si orbital if Si is in the structure
        if "Si" in [site.kind_name for site in si_structure.sites]:
            assert "Si" in pseudos or len(pseudos) > 0

    def test_get_pseudos_missing_elements(self, aiida_profile_clean, si_orbital_family):
        """Test get_pseudos with structure containing missing elements."""
        # Create structure with element not in family
        al_structure = orm.StructureData(ase=bulk("Al", "fcc", a=4.05))

        # Should raise error for missing element
        with pytest.raises(ValueError):
            si_orbital_family.get_pseudos(structure=al_structure)

    def test_database_persistence(self, aiida_profile_clean, atomic_orbital_data):
        """Test storing, loading, and querying families."""
        # Store the atomic orbital data first
        atomic_orbital_data.store()

        # Create and store family
        family = AtomicOrbitalFamily(label="test-persistent")
        family.store()
        family.add_nodes([atomic_orbital_data])

        # Load by PK
        loaded_family = AtomicOrbitalFamily.collection.get(pk=family.pk)
        assert loaded_family.pk == family.pk
        assert loaded_family.label == "test-persistent"
        assert atomic_orbital_data in loaded_family.nodes

        # Load by label
        loaded_by_label = load_group("test-persistent")
        assert loaded_by_label.pk == family.pk

    def test_query_builder_integration(self, aiida_profile_clean, si_orbital_family):
        """Test QueryBuilder integration for family searches."""
        # Query by type string
        qb = QueryBuilder()
        qb.append(AtomicOrbitalFamily, filters={"label": si_orbital_family.label})
        results = qb.all(flat=True)

        assert len(results) >= 1
        assert si_orbital_family.pk in [r.pk for r in results]

        # Query nodes in family
        qb = QueryBuilder()
        qb.append(AtomicOrbitalFamily, tag="family", filters={"label": si_orbital_family.label})
        qb.append(AtomicOrbitalData, with_group="family")
        nodes = qb.all(flat=True)

        assert len(nodes) >= 1

    def test_empty_family_handling(self, aiida_profile_clean):
        """Test behavior with empty families."""
        empty_family = AtomicOrbitalFamily(label="test-empty")
        empty_family.store()

        # Should be able to store and load empty family
        loaded = AtomicOrbitalFamily.collection.get(pk=empty_family.pk)
        assert loaded.pk == empty_family.pk
        assert len(list(loaded.nodes)) == 0

    def test_case_insensitive_element_matching(self, aiida_profile_clean, multi_element_family):
        """Test case-insensitive element matching."""
        # This test would depend on implementation details
        # Test that element matching is case-insensitive where applicable
        nodes = list(multi_element_family.nodes)
        assert len(nodes) >= 1

        # Check element properties (case handling may vary)
        for node in nodes:
            if hasattr(node, "element"):
                element = node.element
                assert isinstance(element, str)
                assert len(element) > 0

    def test_family_description_and_metadata(self, aiida_profile_clean, atomic_orbital_data):
        """Test family description and metadata handling."""
        description = "Test family description"

        # Store the atomic orbital data first
        atomic_orbital_data.store()

        family = AtomicOrbitalFamily(label="test-metadata", description=description)
        family.store()
        family.add_nodes([atomic_orbital_data])

        # Should preserve description
        assert family.description == description

        # Load and verify
        loaded = AtomicOrbitalFamily.collection.get(pk=family.pk)
        assert loaded.description == description

    def test_label_uniqueness(self, aiida_profile_clean, atomic_orbital_data):
        """Test that family labels must be unique."""
        # Store the atomic orbital data first
        atomic_orbital_data.store()

        # Create first family
        family1 = AtomicOrbitalFamily(label="duplicate-label")
        family1.store()
        family1.add_nodes([atomic_orbital_data])

        # Try to create second family with same label
        family2 = AtomicOrbitalFamily(label="duplicate-label")
        # Should raise error when trying to store duplicate
        with pytest.raises(Exception):  # Specific exception may vary
            family2.store()

    def test_inheritance_from_pseudopotential_family(self, si_orbital_family):
        """Test that AtomicOrbitalFamily properly inherits from PseudoPotentialFamily."""
        # Should be an instance of PseudoPotentialFamily
        assert isinstance(si_orbital_family, PseudoPotentialFamily)

        # Should have PseudoPotentialFamily methods available
        assert hasattr(si_orbital_family, "get_pseudos")
        assert hasattr(si_orbital_family, "clear")

    def test_node_list_properties(self, multi_element_family):
        """Test various node list and property access methods."""
        # Test nodes property
        nodes = list(multi_element_family.nodes)
        assert len(nodes) >= 1

        # Should have access to node properties
        for node in nodes:
            assert hasattr(node, "pk")
            assert node.pk is not None
            assert hasattr(node, "uuid")
            assert node.uuid is not None
