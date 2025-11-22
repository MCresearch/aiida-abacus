"""Tests for AtomicOrbitalData class."""

import pytest
from aiida.common.exceptions import ValidationError
from aiida_abacus.data.orbital import AtomicOrbitalData


class TestAtomicOrbitalData:
    """Test the AtomicOrbitalData class functionality."""

    def test_creation_and_file_handling(self, aiida_profile_clean, data_folder, si_orbital_file):
        """Test AtomicOrbitalData creation and file handling."""
        # Test basic creation with both pseudopotential and orbital files
        pseudo_file = data_folder / "pseudos" / "Si.upf"
        orbital_data = AtomicOrbitalData(pseudo_file, si_orbital_file)

        # Verify that both files are stored
        assert orbital_data.filename == "Si.upf"
        assert orbital_data.filename_second == si_orbital_file.name

        # Verify repository contains both files
        repository_files = orbital_data.base.repository.list_object_names()
        assert "Si.upf" in repository_files
        assert si_orbital_file.name in repository_files

        # Verify MD5 calculation for orbital file
        assert orbital_data.md5_orbital is not None
        assert isinstance(orbital_data.md5_orbital, str)
        assert len(orbital_data.md5_orbital) == 32  # MD5 hash length

    def test_creation_with_custom_filenames(self, aiida_profile_clean, data_folder, si_orbital_file):
        """Test AtomicOrbitalData creation with custom filenames."""
        pseudo_file = data_folder / "pseudos" / "Si.upf"
        custom_pseudo_name = "custom_pseudo.upf"
        custom_orbital_name = "custom_orbital.orb"

        orbital_data = AtomicOrbitalData(
            pseudo_file, si_orbital_file, filename=custom_pseudo_name, orbital_filename=custom_orbital_name
        )

        # Verify custom filenames are used
        assert orbital_data.filename == custom_pseudo_name
        assert orbital_data.filename_second == custom_orbital_name

    def test_properties_and_metadata(self, atomic_orbital_data):
        """Test all properties and metadata access."""
        # Test properties that should return None by default (not set)
        assert atomic_orbital_data.cut_off_energy is None
        assert atomic_orbital_data.functional is None
        assert atomic_orbital_data.orbital_type is None
        assert atomic_orbital_data.electron_config is None

        # Test properties that should have values
        assert atomic_orbital_data.filename_second is not None
        assert isinstance(atomic_orbital_data.filename_second, str)
        assert atomic_orbital_data.md5_orbital is not None
        assert isinstance(atomic_orbital_data.md5_orbital, str)

        # Test that md5_orbital matches actual file MD5
        from aiida.common.files import md5_from_filelike

        with atomic_orbital_data.open_second(mode="rb") as handle:
            expected_md5 = md5_from_filelike(handle)
        assert atomic_orbital_data.md5_orbital == expected_md5

    def test_file_access_methods(self, atomic_orbital_data):
        """Test file access methods for orbital file."""
        # Test open_second with text mode
        with atomic_orbital_data.open_second(mode="r") as handle:
            content = handle.read()
            assert isinstance(content, str)
            assert len(content) > 0
            # Check for typical orbital file content
            assert "Element" in content or "Atomic" in content

        # Test open_second with binary mode
        with atomic_orbital_data.open_second(mode="rb") as handle:
            content = handle.read()
            assert isinstance(content, bytes)
            assert len(content) > 0

        # Test get_content_second
        text_content = atomic_orbital_data.get_content_second(mode="r")
        assert isinstance(text_content, str)
        assert len(text_content) > 0

        binary_content = atomic_orbital_data.get_content_second(mode="rb")
        assert isinstance(binary_content, bytes)
        assert len(binary_content) > 0

    def test_set_file_second(self, atomic_orbital_data, tmp_path):
        """Test setting a different orbital file."""
        # Create a new orbital file
        new_orbital_content = """Test orbital file content
Element    Test
L    0
Type    Test
E    -1.000000
N    2
Radial    0.0    1.0
R2    1.0    0.5
"""
        new_orbital_file = tmp_path / "test.orb"
        new_orbital_file.write_text(new_orbital_content)

        # Set the new orbital file
        original_filename = atomic_orbital_data.filename_second
        atomic_orbital_data.set_file_second(new_orbital_file, filename="test.orb")

        # Verify the file was updated
        assert atomic_orbital_data.filename_second == "test.orb"
        assert atomic_orbital_data.filename_second != original_filename

        # Verify content matches new file
        content = atomic_orbital_data.get_content_second(mode="r")
        assert "Test orbital file content" in content

    def test_md5_validation(self, atomic_orbital_data):
        """Test MD5 validation functionality."""
        # Get the current MD5
        current_md5 = atomic_orbital_data.md5_orbital

        # Test validate_md5_orbital with correct MD5
        # Should not raise an exception
        atomic_orbital_data.validate_md5_orbital(current_md5)

        # Test validate_md5_orbital with incorrect MD5
        with pytest.raises(ValueError, match="md5 does not match"):
            atomic_orbital_data.validate_md5_orbital("incorrect_md5_hash")

        # Test md5_orbital setter with correct MD5
        new_md5 = current_md5  # Use the same valid MD5
        atomic_orbital_data.md5_orbital = new_md5
        assert atomic_orbital_data.md5_orbital == new_md5

        # Test md5_orbital setter with incorrect MD5
        with pytest.raises(ValueError, match="md5 does not match"):
            atomic_orbital_data.md5_orbital = "incorrect_md5_hash"

    def test_database_integration(self, aiida_profile_clean, data_folder, si_orbital_file):
        """Test database integration and get_or_create functionality."""
        pseudo_file = data_folder / "pseudos" / "Si.upf"

        # Create first instance
        orbital_data1 = AtomicOrbitalData(pseudo_file, si_orbital_file)
        orbital_data1.store()

        # Try to create second instance with same files
        # This should return the existing instance from database
        with open(pseudo_file, "rb") as pseudo_handle, open(si_orbital_file, "rb") as orbital_handle:
            orbital_data2 = AtomicOrbitalData.get_or_create(
                pseudo_handle, orbital_handle, filename="Si.upf", filename_orbital=si_orbital_file.name
            )

        # The second instance should be the same as the first (same UUID)
        assert orbital_data1.uuid == orbital_data2.uuid
        assert orbital_data2.is_stored

    def test_get_or_create_duplicate_detection(self, aiida_profile_clean, data_folder, si_orbital_file):
        """Test that get_or_create properly detects and returns existing nodes based on MD5 checksums."""
        pseudo_file = data_folder / "pseudos" / "Si.upf"

        # Store first instance
        orbital_data1 = AtomicOrbitalData.get_or_create(pseudo_file, si_orbital_file)
        orbital_data1.store()

        # Test that get_or_create returns the same instance when called with same files
        orbital_data2 = AtomicOrbitalData.get_or_create(pseudo_file, si_orbital_file)
        assert orbital_data1.uuid == orbital_data2.uuid

        # Test that get_or_create creates new instance when files are different
        mg_orbital_file = data_folder / "orbitals" / "Mg_gga_9au_100Ry_2s1p.orb"
        orbital_data3 = AtomicOrbitalData.get_or_create(pseudo_file, mg_orbital_file)
        assert orbital_data3.uuid != orbital_data1.uuid
        assert not orbital_data3.is_stored

        # Store the new instance
        orbital_data3.store()

        # Now verify that get_or_create returns this new instance for Mg orbital
        orbital_data4 = AtomicOrbitalData.get_or_create(pseudo_file, mg_orbital_file)
        assert orbital_data3.uuid == orbital_data4.uuid
        assert orbital_data4.is_stored

    def test_error_handling(self, aiida_profile_clean, data_folder):
        """Test error handling for various invalid scenarios."""
        pseudo_file = data_folder / "pseudos" / "Si.upf"

        # Test with relative path (should fail first)
        with pytest.raises(ValueError, match=r"path .* is not absolute"):
            AtomicOrbitalData(pseudo_file, "relative/path.orb")

        # Test with non-existent orbital file (absolute path but doesn't exist)
        non_existent = "/tmp/non_existent_file.orb"
        with pytest.raises(ValueError, match="does not correspond to an existing file"):
            AtomicOrbitalData(pseudo_file, non_existent)

        # Test validation failure for repository mismatch
        valid_orbital_file = data_folder / "orbitals" / "Si_gga_7au_100Ry_2s2p1d.orb"
        orbital_data = AtomicOrbitalData(pseudo_file, valid_orbital_file)

        # Manually corrupt the repository to trigger validation error
        orbital_data.base.repository.delete_object(valid_orbital_file.name)

        with pytest.raises(ValidationError, match=r"respository files .* do not match"):
            orbital_data._validate()

    def test_validation_method(self, atomic_orbital_data):
        """Test the _validate method for repository consistency."""
        # The _validate method should pass for a properly created instance
        assert atomic_orbital_data._validate() is True

    def test_inheritance_from_upf_data(self, atomic_orbital_data):
        """Test that AtomicOrbitalData properly inherits from UpfData."""
        from aiida_pseudo.data.pseudo import UpfData

        # Should be an instance of UpfData
        assert isinstance(atomic_orbital_data, UpfData)

        # Should have UpfData methods available
        assert hasattr(atomic_orbital_data, "element")
        assert hasattr(atomic_orbital_data, "md5")  # From UpfData
