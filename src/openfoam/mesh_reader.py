"""Чтение расчётной сетки OpenFOAM из директории ``constant/polyMesh/``.

Разбирает файлы ``points``, ``faces`` и ``boundary``, предоставляя
доступ к координатам узлов, топологии граней и списку патчей.

Example:
    >>> from src.openfoam.mesh_reader import MeshReader
    >>> mesh = MeshReader("tests/cases/airFoil2D")
    >>> print(f"Узлов: {mesh.n_points}, граней: {mesh.n_faces}")
    >>> for p in mesh.patches:
    ...     print(f"  {p.name}: {p.n_faces} faces")
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from src.model import PatchInfo


class MeshReader:
    """Ридер сетки OpenFOAM polyMesh.

    Attributes:
        case_path: Путь к директории кейса OpenFOAM.
        points: Массив координат узлов, форма ``(N, 3)``.
        faces: Список граней — каждая грань это список индексов узлов.
        patches: Список структур ``PatchInfo`` с метаданными патчей.
        n_points: Количество узлов.
        n_faces: Количество граней.
    """

    def __init__(self, case_path: str | Path) -> None:
        """Инициализирует MeshReader и загружает данные сетки.

        Args:
            case_path: Путь к директории кейса OpenFOAM,
                содержащей ``constant/polyMesh/``.

        Raises:
            FileNotFoundError: Если директория ``polyMesh`` не найдена.
        """
        self.case_path = Path(case_path)
        poly_dir = self.case_path / "constant" / "polyMesh"
        if not poly_dir.is_dir():
            raise FileNotFoundError(f"polyMesh directory not found: {poly_dir}")

        self.points = self._read_points(poly_dir / "points")
        self.faces = self._read_faces(poly_dir / "faces")
        self.patches = self._read_boundary(poly_dir / "boundary")
        self.n_points = len(self.points)
        self.n_faces = len(self.faces)

    def get_patch_faces(self, patch_name: str) -> list[list[int]]:
        """Возвращает список граней для заданного патча.

        Args:
            patch_name: Имя патча из ``constant/polyMesh/boundary``.

        Returns:
            Список граней, каждая грань — список индексов узлов.

        Raises:
            KeyError: Если патч с таким именем не найден.

        Example:
            >>> mesh = MeshReader("tests/cases/airFoil2D")
            >>> inlet_faces = mesh.get_patch_faces("inlet")
            >>> print(f"Inlet: {len(inlet_faces)} faces")
        """
        for patch in self.patches:
            if patch.name == patch_name:
                start = patch.start_face
                end = start + patch.n_faces
                return self.faces[start:end]
        raise KeyError(f"Patch '{patch_name}' not found")

    def get_patch_points(self, patch_name: str) -> np.ndarray:
        """Возвращает координаты узлов, используемых в гранях патча.

        Args:
            patch_name: Имя патча.

        Returns:
            Массив уникальных точек формы ``(M, 3)``.

        Raises:
            KeyError: Если патч не найден.
        """
        faces = self.get_patch_faces(patch_name)
        indices = set()
        for face in faces:
            indices.update(face)
        idx_sorted = sorted(indices)
        return self.points[idx_sorted]

    def _read_points(self, filepath: Path) -> np.ndarray:
        """Парсит файл ``points`` в массив координат."""
        text = filepath.read_text(encoding="utf-8", errors="replace")
        text = self._strip_header(text)

        coords: list[tuple[float, float, float]] = []
        for match in re.finditer(
            r"\(\s*([eE\d.+-]+)\s+([eE\d.+-]+)\s+([eE\d.+-]+)\s*\)", text
        ):
            coords.append((
                float(match.group(1)),
                float(match.group(2)),
                float(match.group(3)),
            ))
        return np.array(coords, dtype=np.float64)

    def _read_faces(self, filepath: Path) -> list[list[int]]:
        """Парсит файл ``faces`` — каждая грань вида ``N(i0 i1 ... iN-1)``."""
        text = filepath.read_text(encoding="utf-8", errors="replace")
        text = self._strip_header(text)

        faces: list[list[int]] = []
        for match in re.finditer(r"\d+\(([^)]+)\)", text):
            indices = [int(x) for x in match.group(1).split()]
            faces.append(indices)
        return faces

    def _read_boundary(self, filepath: Path) -> list[PatchInfo]:
        """Парсит файл ``boundary`` — список патчей с метаданными.

        Формат: после заголовка идёт число патчей, затем скобки ``( ... )``,
        внутри которых чередуются имя патча и блок ``{ type ...; nFaces ...; ... }``.
        """
        text = filepath.read_text(encoding="utf-8", errors="replace")
        text = self._strip_header(text)

        text = re.sub(r"//[^\n]*", "", text)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

        paren_start = text.find("(")
        if paren_start < 0:
            return []
        paren_end = text.rfind(")")
        inner = text[paren_start + 1 : paren_end]

        patches: list[PatchInfo] = []
        block_re = re.compile(
            r"(\w+)\s*\{([^}]*)\}", re.DOTALL
        )
        for m in block_re.finditer(inner):
            name = m.group(1)
            body = m.group(2)

            def _val(key: str) -> str:
                pat = re.compile(rf"{key}\s+(\S+)\s*;")
                match = pat.search(body)
                return match.group(1) if match else ""

            patches.append(PatchInfo(
                name=name,
                patch_type=_val("type"),
                n_faces=int(_val("nFaces") or 0),
                start_face=int(_val("startFace") or 0),
            ))
        return patches

    @staticmethod
    def _strip_header(text: str) -> str:
        """Удаляет заголовок ``FoamFile { ... }`` и предшествующие комментарии."""
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        text = re.sub(r"//[^\n]*", "", text)
        text = re.sub(
            r"FoamFile\s*\{[^}]*\}", "", text, count=1
        )
        return text
