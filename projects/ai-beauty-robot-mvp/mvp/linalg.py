"""아주 작은 선형대수 유틸 (numpy 없이 동작).

LinUCB 는 d x d 역행렬이 필요한데, MVP 의 컨텍스트 차원 d 는 10 안팎이라
가우스-조던 소거로 충분합니다. numpy 를 쓸 수 있는 환경이면 교체하세요.
"""
from __future__ import annotations

Matrix = list[list[float]]
Vector = list[float]


def identity(n: int, scale: float = 1.0) -> Matrix:
    return [[scale if i == j else 0.0 for j in range(n)] for i in range(n)]


def zeros(n: int) -> Vector:
    return [0.0] * n


def outer_add(A: Matrix, x: Vector, weight: float = 1.0) -> None:
    """A += weight * x x^T (제자리 갱신)."""
    n = len(x)
    for i in range(n):
        xi = x[i] * weight
        row = A[i]
        for j in range(n):
            row[j] += xi * x[j]


def matvec(A: Matrix, x: Vector) -> Vector:
    return [sum(a * b for a, b in zip(row, x)) for row in A]


def dot(a: Vector, b: Vector) -> float:
    return sum(x * y for x, y in zip(a, b))


def inverse(A: Matrix) -> Matrix:
    """가우스-조던 역행렬. 특이행렬이면 대각에 미세 리지를 더해 재시도."""
    n = len(A)
    aug = [list(A[i]) + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            ridged = [list(row) for row in A]
            for i in range(n):
                ridged[i][i] += 1e-6
            if all(abs(ridged[i][i] - A[i][i]) < 1e-12 for i in range(n)):
                raise ValueError("singular matrix")
            return inverse(ridged)
        aug[col], aug[pivot] = aug[pivot], aug[col]
        pv = aug[col][col]
        aug[col] = [v / pv for v in aug[col]]
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            if factor:
                aug[r] = [v - factor * w for v, w in zip(aug[r], aug[col])]
    return [row[n:] for row in aug]
