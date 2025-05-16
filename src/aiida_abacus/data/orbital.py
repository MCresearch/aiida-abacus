import contextlib
import os
import pathlib
import typing as t

from aiida import orm
from aiida.common import exceptions
from aiida.common.files import md5_from_filelike
from aiida_pseudo.data.pseudo import UpfData

FilePath = t.Union[str, pathlib.PurePosixPath]


class DualfileMixin:
    """
    A Mixin class which can be used with a sub-class of ``SinglefileData`` to store a second file.
    """

    @property
    def filename_second(self):
        return self.base.attributes.get("filename_second")

    @t.overload
    @contextlib.contextmanager
    def open_second(self, path: FilePath, mode: t.Literal["r"] = ...) -> t.Iterator[t.TextIO]: ...

    @t.overload
    @contextlib.contextmanager
    def open_second(self, path: FilePath, mode: t.Literal["rb"]) -> t.Iterator[t.BinaryIO]: ...

    @t.overload
    @contextlib.contextmanager
    def open_second(  # type: ignore[overload-overlap]
        self, path: None = None, mode: t.Literal["r"] = ...
    ) -> t.Iterator[t.TextIO]: ...

    @t.overload
    @contextlib.contextmanager
    def open_second(self, path: None = None, mode: t.Literal["rb"] = ...) -> t.Iterator[t.BinaryIO]: ...

    @contextlib.contextmanager
    def open_second(
        self, path: FilePath | None = None, mode: t.Literal["r", "rb"] = "r"
    ) -> t.Iterator[t.BinaryIO] | t.Iterator[t.TextIO]:
        """Return an open file handle to the content of this data node.

        :param path: the relative path of the object within the repository.
        :param mode: the mode with which to open the file handle (default: read mode)
        :return: a file handle
        """
        if path is None:
            path = self.filename_second

        with self.base.repository.open(path, mode=mode) as handle:
            yield handle

    def get_content_second(self, mode: str = "r") -> str | bytes:
        """Return the content of the single file stored for this data node.

        :param mode: the mode with which to open the file handle (default: read mode)
        :return: the content of the file as a string or bytes, depending on ``mode``.
        """
        with self.open_second(mode=mode) as handle:  # type: ignore[call-overload]
            return handle.read()

    def set_file_second(self, file: str | pathlib.Path | t.IO, filename: str | pathlib.Path | None = None) -> None:
        """Store the content of the file in the node's repository, deleting any other existing objects.

        :param file: an absolute filepath or filelike object whose contents to copy
            Hint: Pass io.BytesIO(b"my string") to construct the file directly from a string.
        :param filename: specify filename to use (defaults to name of provided file).
        """
        if isinstance(file, (str, pathlib.Path)):
            is_filelike = False

            key = os.path.basename(file)
            if not os.path.isabs(file):
                raise ValueError(f"path `{file}` is not absolute")

            if not os.path.isfile(file):
                raise ValueError(f"path `{file}` does not correspond to an existing file")
        else:
            is_filelike = True
            try:
                key = os.path.basename(file.name)
            except AttributeError:
                key = self.DEFAULT_FILENAME

        key = str(filename) if filename is not None else key
        assert key != self.filename, f"filename `{key}` is already used by this node"
        existing_object_names = self.base.repository.list_object_names()

        try:
            # Remove the 'key' from the list of currently existing objects such that it is not deleted after storing
            existing_object_names.remove(key)
        except ValueError:
            pass

        if is_filelike:
            self.base.repository.put_object_from_filelike(file, key)  # type: ignore[arg-type]
        else:
            self.base.repository.put_object_from_file(file, key)  # type: ignore[arg-type]

        # Delete any other existing objects (minus the current `key` which was already removed from the list)
        for existing_key in existing_object_names:
            if existing_key != self.filename:
                self.base.repository.delete_object(existing_key)

        self.base.attributes.set("filename_second", key)


class AtomicOrbitalData(UpfData, DualfileMixin):
    """
    Abacus orbital data
    This is essentially an UpfData with a second file attached
    """

    _key_md5_orbital = "md5_orbital"
    _key_electron_config = "electron_config"
    _key_cut_off_energy = "cut_off_energy_ry"
    _key_orbital_type = "orbital_type"
    _key_functional = "functional"

    def __init__(
        self,
        file: str | pathlib.Path | t.IO,
        orbital_file: str | pathlib.Path | t.IO,
        filename: str | pathlib.Path | None = None,
        orbital_filename: str | pathlib.Path | None = None,
        **kwargs: t.Any,
    ) -> None:
        """Construct a new instance and set the contents to that of the file.

        :param file: an absolute filepath or filelike object whose contents to copy.
            Hint: Pass io.BytesIO(b"my string") to construct the SinglefileData directly from a string.
        :param filename: specify filename to use (defaults to name of provided file).
        """
        super().__init__(file, filename, **kwargs)
        if orbital_file is not None:
            self.set_file_second(orbital_file, filename=orbital_filename)

    @property
    def cut_off_energy(self) -> float:
        """
        Return the cut off energy used for orbital generation
        """
        return self.base.attributes.get(self._key_cut_off_energy, None)

    @property
    def functional(self) -> t.Optional[str]:
        """Return the functional used for orbital generation"""
        return self.base.attributes.get(self._key_functional, None)

    @property
    def orbital_type(self) -> t.Optional[str]:
        """Return the orbital type used for orbital generation"""
        return self.base.attributes.get(self._key_orbital_type, None)

    @property
    def electron_config(self) -> t.Optional[str]:
        """Return the orbital type used for orbital generation"""
        return self.base.attributes.get(self._key_electron_config, None)

    @property
    def md5_orbital(self) -> t.Optional[int]:
        """Return the md5.

        :return: the md5 of the stored file.
        """
        return self.base.attributes.get(self._key_md5_orbital, None)

    @md5_orbital.setter
    def md5_orbital(self, value: str):
        """Set the md5.

        :param value: the md5 checksum.
        :raises ValueError: if the md5 does not match that of the currently stored file.
        """
        self.validate_md5_orbital(value)
        self.base.attributes.set(self._key_md5_orbital, value)

    def validate_md5_orbital(self, md5: str):
        """Validate that the md5 checksum matches that of the currently stored file.

        :param value: the md5 checksum.
        :raises ValueError: if the md5 does not match that of the currently stored file.
        """
        with self.open_second(mode="rb") as handle:
            md5_file = md5_from_filelike(handle)
            if md5 != md5_file:
                raise ValueError(f"md5 does not match that of stored file: {md5} != {md5_file}")

    @classmethod
    def get_or_create(
        cls,
        source: t.Union[str, pathlib.Path, t.BinaryIO],
        source_orbital: t.Union[str, pathlib.Path, t.BinaryIO],
        filename: t.Optional[str] = None,
        filename_orbital: t.Optional[str] = None,
    ):
        """Get pseudopotenial data node from database with matching md5 checksum or create a new one if not existent.

        :param source: the source pseudopotential content, either a binary stream, or a ``str`` or ``Path`` to the path
            of the file on disk, which can be relative or absolute.
        :param filename: optional explicit filename to give to the file stored in the repository.
        :return: instance of ``PseudoPotentialData``, stored if taken from database, unstored otherwise.
        :raises TypeError: if the source is not a ``str``, ``pathlib.Path`` instance or binary stream.
        :raises FileNotFoundError: if the source is a filepath but does not exist.
        """
        source = cls.prepare_source(source)
        source_orbital = cls.prepare_source(source_orbital)

        query = orm.QueryBuilder()
        query.append(
            cls,
            subclassing=False,
            filters={
                f"attributes.{cls._key_md5}": md5_from_filelike(source),
                f"attributes.{cls._key_md5_orbital}": md5_from_filelike(source_orbital),
            },
        )

        orb = query.first(flat=True)

        if not orb:
            # Seek back to the beginning of the file
            source.seek(0)
            source_orbital.seek(0)
            orb = cls(source, source_orbital, filename, filename_orbital)
        return orb

    def _validate(self) -> bool:
        """Ensure that there is one object stored in the repository, whose key matches value set for `filename` attr."""
        orm.Data._validate(self)
        try:
            filename = self.filename
            filename_second = self.filename_second
        except AttributeError:
            raise exceptions.ValidationError("the `filename` attribute is not set.")

        objects = self.base.repository.list_object_names()

        if sorted([filename, filename_second]) != sorted(objects):
            raise exceptions.ValidationError(
                f"respository files {objects} do not match the `filename` and `filename_second` "
                "attribute `{filename}` `{filename_second}`."
            )

        return True
