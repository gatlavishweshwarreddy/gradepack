import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from slugify import slugify


def test_simple():
    assert slugify("Hello World") == "hello-world"


def test_leading_trailing_spaces():
    assert slugify("  Hello   World  ") == "hello-world"


def test_punctuation():
    assert slugify("Hello, World!") == "hello-world"


def test_digits():
    assert slugify("Python 3.11") == "python-3-11"


def test_already_slug():
    assert slugify("hello-world") == "hello-world"


def test_uppercase():
    assert slugify("UPPER CASE") == "upper-case"
