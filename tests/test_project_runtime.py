import sys


def test_project_requires_python_311_or_newer():
    assert sys.version_info >= (3, 11)
