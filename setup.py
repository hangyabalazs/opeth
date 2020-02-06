import setuptools

with open("README.rst", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="opeth",
    version="0.1.3",
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
    entry_points = {
        'console_scripts': ['opeth=opeth.gui:main'],
    },

    install_requires=[
      'pyqtgraph',
      'pyzmq',
      'PySide2'
    ],
    include_package_data=True,
    python_requires='<3.8',
)