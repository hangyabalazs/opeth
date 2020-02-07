import setuptools

with open("README.rst", "r") as fh:
    long_description = fh.read()

exec(open('opeth/version.py').read())

setuptools.setup(
    name="opeth",
    version=__version__,
    author="Andras Szell",
    author_email="szell.andris@gmail.com",
    description="Online Peri-Event Histogram for Open Ephys ZMQ plugin",
    long_description=long_description,
    long_description_content_type="text/x-rst",
    url="https://github.com/hangyabalazs/opeth",
    packages=setuptools.find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: OS Independent",
        "Intended Audience :: Science/Research",
    ],
    project_urls={
        'Documentation': 'https://opeth.readthedocs.io/en/latest',
        'Source': 'https://github.com/hangyabalazs/opeth',
    },
    entry_points = {
        'console_scripts': ['opeth=opeth.gui:main'],
    },

    install_requires=[
      'pyqtgraph',
      'pyzmq',
      'PySide'
    ],
    include_package_data=True,
    python_requires='<3.8',
)