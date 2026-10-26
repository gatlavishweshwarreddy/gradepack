"""
gradepack CLI — entry point: python -m gradepack
"""
import sys
from gradepack import cli

cli.main(sys.argv[1:])
