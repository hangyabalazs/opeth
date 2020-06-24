# Before dropping python 2.7 support and moving on to more modern metadata handling, based on
# https://stackoverflow.com/a/16084844/501814:
# Store the version here so:
# 1) we don't load dependencies by storing it in __init__.py
# 2) we can import it in setup.py for the same reason
# 3) we can import it into your module module

__version__ = '0.1b1'