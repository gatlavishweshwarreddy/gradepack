import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from matrix import Matrix
import pytest
import random


def _ref_matmul(a, b):
    nr, nc, nk = len(a), len(b[0]), len(b)
    return [[sum(a[i][k] * b[k][j] for k in range(nk)) for j in range(nc)]
            for i in range(nr)]


def test_integer_matmul_exact():
    a = Matrix([[1, 0], [0, 1]])
    b = Matrix([[3, 4], [5, 6]])
    result = (a @ b).rows
    assert result == [[3, 4], [5, 6]]


def test_fractional_result_preserved():
    a = Matrix([[1, 1], [1, 2]])
    b = Matrix([[1, 1], [1, 1]])
    result = (a @ b).rows
    expected = _ref_matmul([[1, 1], [1, 2]], [[1, 1], [1, 1]])
    assert result == expected


def test_scale_with_float_factor():
    m = Matrix([[2, 4], [6, 8]])
    scaled = m.scale(0.5).rows
    assert scaled[0][0] == pytest.approx(1.0)
    assert scaled[0][1] == pytest.approx(2.0)


def test_matmul_fractional_intermediate():
    a = Matrix([[1, 2], [3, 4]])
    b = Matrix([[1, 1], [1, 2]])
    result = (a @ b).rows
    expected = _ref_matmul([[1, 2], [3, 4]], [[1, 1], [1, 2]])
    for i in range(2):
        for j in range(2):
            assert result[i][j] == pytest.approx(expected[i][j]), \
                f"[{i}][{j}]: got {result[i][j]}, expected {expected[i][j]}"


@pytest.mark.parametrize("seed", [0, 1, 7])
def test_random_float_matmul(seed):
    rng = random.Random(seed)
    a_data = [[rng.uniform(-5, 5) for _ in range(3)] for _ in range(3)]
    b_data = [[rng.uniform(-5, 5) for _ in range(3)] for _ in range(3)]
    a = Matrix(a_data)
    b = Matrix(b_data)
    result = (a @ b).rows
    expected = _ref_matmul(a_data, b_data)
    for i in range(3):
        for j in range(3):
            assert result[i][j] == pytest.approx(expected[i][j], rel=1e-5)
