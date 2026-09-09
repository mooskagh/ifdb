import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self

_RAR_SIGNATURE = b"Rar!\x1a\x07"


class ArchiveError(Exception):
    pass


class BadArchiveError(ArchiveError):
    pass


class ArchiveToolNotFoundError(ArchiveError):
    pass


class Archive(Protocol):
    def namelist(self) -> list[str]: ...

    def extract(self, destination: Path) -> None: ...

    def close(self) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...


class ZipArchive:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self._zip = zipfile.ZipFile(path, "r")
        except zipfile.BadZipFile as exc:
            raise BadArchiveError(f"Bad zip file: {path}") from exc

    def namelist(self) -> list[str]:
        return [name.replace("\\", "/") for name in self._zip.namelist()]

    def extract(self, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        try:
            self._zip.extractall(destination)
        except zipfile.BadZipFile as exc:
            raise BadArchiveError(
                f"Failed to extract zip file: {self.path}"
            ) from exc

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()


class UnarArchive:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lsar_bin = shutil.which("lsar")
        self._unar_bin = shutil.which("unar")
        if not self._lsar_bin or not self._unar_bin:
            raise ArchiveToolNotFoundError("unar and lsar tools are required")

    def namelist(self) -> list[str]:
        assert self._lsar_bin is not None
        try:
            result = subprocess.run(
                [self._lsar_bin, "-j", str(self.path)],
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise ArchiveError(f"Failed to run lsar: {exc}") from exc

        if result.returncode != 0:
            raise BadArchiveError(
                f"lsar returned non-zero exit code for {self.path}"
            )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise BadArchiveError(
                f"Failed to parse lsar output for {self.path}"
            ) from exc

        names: list[str] = []
        for item in data.get("lsarContents", []):
            name = item.get("XADFileName")
            if isinstance(name, str):
                names.append(name.replace("\\", "/"))
        return names

    def extract(self, destination: Path) -> None:
        assert self._unar_bin is not None
        destination.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                [
                    self._unar_bin,
                    "-D",
                    "-f",
                    "-o",
                    str(destination),
                    str(self.path),
                ],
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise ArchiveError(f"Failed to run unar: {exc}") from exc

        if result.returncode != 0:
            raise BadArchiveError(
                f"unar returned non-zero exit code for {self.path}"
            )

    def close(self) -> None:
        pass

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()


def is_rarfile(path: Path | str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(_RAR_SIGNATURE)) == _RAR_SIGNATURE
    except OSError:
        return False


def open_archive(path: Path | str) -> Archive:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    if zipfile.is_zipfile(file_path):
        return ZipArchive(file_path)

    if is_rarfile(file_path) or file_path.suffix.lower() == ".rar":
        return UnarArchive(file_path)

    if shutil.which("lsar") and shutil.which("unar"):
        unar_archive = UnarArchive(file_path)
        try:
            unar_archive.namelist()
            return unar_archive
        except ArchiveError:
            pass

    raise BadArchiveError(f"Unsupported or invalid archive: {file_path}")


def list_archive_members(path: Path | str) -> list[str]:
    with open_archive(path) as archive:
        return archive.namelist()


def extract_archive(path: Path | str, destination: Path | str) -> None:
    with open_archive(path) as archive:
        archive.extract(Path(destination))


def repack_to_zip(source: Path | str, destination: Path | str) -> None:
    source_path = Path(source)
    dest_path = Path(destination)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if zipfile.is_zipfile(source_path):
        shutil.copyfile(source_path, dest_path)
        return

    with tempfile.TemporaryDirectory() as extract_dir:
        extract_archive(source_path, Path(extract_dir))
        with zipfile.ZipFile(
            dest_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            for root, _, files in os.walk(extract_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(extract_dir)
                    zf.write(file_path, arcname=str(arcname))
