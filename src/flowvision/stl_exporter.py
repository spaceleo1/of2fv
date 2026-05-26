"""Экспорт поверхностных патчей OpenFOAM polyMesh в binary STL-файлы.

Для каждого патча извлекаются грани, разбиваются на треугольники
(fan triangulation) и записываются в формат binary STL, который
FlowVision может импортировать напрямую.

Example:
    >>> from src.openfoam.mesh_reader import MeshReader
    >>> from src.flowvision.stl_exporter import export_patch_stl
    >>> mesh = MeshReader("tests/cases/airFoil2D")
    >>> export_patch_stl(mesh, "inlet", "/tmp/inlet.stl")
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from src.openfoam.mesh_reader import MeshReader


def export_patch_stl(
    mesh: MeshReader,
    patch_name: str,
    output_path: str | Path,
) -> int:
    """Экспортирует один патч polyMesh в binary STL-файл.

    Полигональные грани разбиваются на треугольники через fan
    triangulation (первая вершина — центр веера).

    Args:
        mesh: Загруженный ``MeshReader``.
        patch_name: Имя патча из ``polyMesh/boundary``.
        output_path: Путь для записи STL-файла.

    Returns:
        Количество треугольников в записанном файле.

    Raises:
        KeyError: Если патч не найден.
        IOError: Если не удалось записать файл.

    Example:
        >>> n = export_patch_stl(mesh, "walls", "output/walls.stl")
        >>> print(f"Written {n} triangles")
    """
    faces = mesh.get_patch_faces(patch_name)
    points = mesh.points

    triangles, normals = _triangulate_faces(faces, points)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_binary_stl(triangles, normals, output_path)

    return len(triangles)


def export_all_patches(
    mesh: MeshReader,
    output_dir: str | Path,
    skip_empty: bool = True,
) -> dict[str, int]:
    """Экспортирует все патчи polyMesh в отдельные STL-файлы.

    Патчи типа ``empty`` пропускаются по умолчанию (2D-грани
    нулевой толщины).

    Args:
        mesh: Загруженный ``MeshReader``.
        output_dir: Директория для STL-файлов.
        skip_empty: Пропускать патчи типа ``empty``.

    Returns:
        Словарь ``{имя_патча: кол-во_треугольников}``.

    Example:
        >>> from src.openfoam.mesh_reader import MeshReader
        >>> mesh = MeshReader("tests/cases/airFoil2D")
        >>> result = export_all_patches(mesh, "output/stl")
        >>> for name, n in result.items():
        ...     print(f"  {name}: {n} triangles")
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    results: dict[str, int] = {}
    for patch in mesh.patches:
        if skip_empty and patch.patch_type == "empty":
            continue
        stl_path = out / f"{patch.name}.stl"
        n_tris = export_patch_stl(mesh, patch.name, stl_path)
        results[patch.name] = n_tris

    return results


def _triangulate_faces(
    faces: list[list[int]],
    points: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Разбивает полигональные грани на треугольники (fan triangulation).

    Args:
        faces: Список граней — каждая грань это список индексов узлов.
        points: Массив координат всех узлов, форма ``(N, 3)``.

    Returns:
        Кортеж ``(triangles, normals)`` — массивы формы ``(M, 3, 3)``
        и ``(M, 3)`` соответственно.
    """
    tris: list[np.ndarray] = []
    norms: list[np.ndarray] = []

    for face in faces:
        n_verts = len(face)
        if n_verts < 3:
            continue

        v0 = points[face[0]]
        for i in range(1, n_verts - 1):
            v1 = points[face[i]]
            v2 = points[face[i + 1]]

            normal = np.cross(v1 - v0, v2 - v0)
            norm_len = np.linalg.norm(normal)
            if norm_len > 0:
                normal = normal / norm_len

            tris.append(np.array([v0, v1, v2]))
            norms.append(normal)

    if not tris:
        return np.empty((0, 3, 3)), np.empty((0, 3))

    return np.array(tris), np.array(norms)


def _write_binary_stl(
    triangles: np.ndarray,
    normals: np.ndarray,
    filepath: Path,
) -> None:
    """Записывает массивы треугольников и нормалей в binary STL.

    Формат binary STL:
    - 80 байт заголовок
    - uint32 количество треугольников
    - Для каждого треугольника: 3×float32 нормаль + 3×(3×float32) вершины + uint16 атрибут

    Args:
        triangles: Массив формы ``(N, 3, 3)``.
        normals: Массив формы ``(N, 3)``.
        filepath: Путь для записи.
    """
    n_tris = len(triangles)

    with open(filepath, "wb") as f:
        header = b"\x00" * 80
        f.write(header)
        f.write(struct.pack("<I", n_tris))

        for i in range(n_tris):
            nx, ny, nz = normals[i].astype(np.float32)
            f.write(struct.pack("<fff", nx, ny, nz))
            for j in range(3):
                x, y, z = triangles[i, j].astype(np.float32)
                f.write(struct.pack("<fff", x, y, z))
            f.write(struct.pack("<H", 0))
