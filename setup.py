#
# Copyright (c) 2013, Prometheus Research, LLC
# Released under MIT license, see `LICENSE` for details.
#


from setuptools import setup, find_packages
import sys


NAME = "pbbt"
VERSION = "0.2.0"
DESCRIPTION = """Pluggable Black-Box Testing toolkit"""
LONG_DESCRIPTION = open('README', 'r').read()
AUTHOR = """Kirill Simonov (Prometheus Research, LLC)"""
AUTHOR_EMAIL = "xi@resolvent.net"
LICENSE = "MIT"
URL = "https://github.com/prometheusresearch/pbbt"
DOWNLOAD_URL = "http://pypi.python.org/pypi/pbbt"
CLASSIFIERS = [
    "Development Status :: 2 - Pre-Alpha",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python",
    "Programming Language :: Python :: 3",
    "Topic :: Utilities",
]
PACKAGES = find_packages('src')
PACKAGE_DIR = {'': 'src'}
INSTALL_REQUIRES = ['PyYAML']
ENTRY_POINTS = {
    'console_scripts': [
        'pbbt = pbbt:main',
    ],
    'distutils.commands': [
        'pbbt = pbbt.setup:pbbt',
    ],
}


setup(name=NAME,
      version=VERSION,
      description=DESCRIPTION,
      long_description=LONG_DESCRIPTION,
      author=AUTHOR,
      author_email=AUTHOR_EMAIL,
      license=LICENSE,
      url=URL,
      download_url=DOWNLOAD_URL,
      classifiers=CLASSIFIERS,
      packages=PACKAGES,
      package_dir=PACKAGE_DIR,
      install_requires=INSTALL_REQUIRES,
      entry_points=ENTRY_POINTS)


