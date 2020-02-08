OPETH
=====

More detailed documentation: https://opeth.readthedocs.io/

.. rtd-inclusion-marker-do-not-remove

Online Peri-Event Time Histogram for `Open Ephys <http://www.open-ephys.org/gui>`_.

Performs spike detection based on raw Open Ephys data exported via `ZeroMQ <https://zeromq.org>`_. 
Requires triggers from Open Ephys for histogram display as spikes are detected around them.

Usage
-----

- Needs `ZMQInterface plugin <https://github.com/bandita137/ZMQInterface>`_ (e.g. in the Open Ephys plugin folder). 
  For Windows a `precompiled dll <https://github.com/bandita137/ZMQInterface/releases/download/v0.2-pre/ZMQInterface.dll>`_ is present. 
- Set up Open Ephys with ZMQInterface plugin. Plugin is recommended to be put after bandpass 
  filter and/or common average reference filter, but spike detector is not required.
- Start with the ``opeth`` command if using the pip package or start with ``python opeth/gui.py`` if running from sources.

Installation
------------

Simplest way is to install the opeth package for Python 2.7 or Python <=3.7 with pip::

    pip install opeth

Then start with::

    opeth

(Python 3.8 support is partially broken as of February 2020.)

Dependencies
^^^^^^^^^^^^

Required non-default packages: pyzmq, pyqtgraph plus one of the qt versions for pyqtgraph, preferably PyQt5,
and also their dependencies (e.g. numpy).

Running from sources
--------------------

After cloning the git repository or extracting a source zip file, multiple methods could work.

Setting up python environment with conda
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Conda builds are not available yet.

Using conda/miniconda, create an ``opeth`` environment issuing the following command in the root dir of opeth::

    conda env create --file environment.yml 
     
which will install all necessary prerequisites for Python 3.7.

Activate the new environment with the command

::

    conda activate opeth

and once activated you may start OPETH with

::

    python opeth/gui.py

Using python 3.8 is not recommended (Feb 2020) as some bugs are to be addressed (most probably residing in pyqtgraph),
but possible using the conda-forge version of pyqtgraph (default environment name will be opeth_python38)::

    conda env create --file env38.yml

Setting up python environment with pip
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Python 3.7 dependencies can be installed with the command

::

    pip install -r requirements.txt


Contributors
------------

Developed by Andras Szell (szell.andris@gmail.com) and other Hangyalab members (http://hangyalab.koki.hu/).

Open Ephys ZMQ plugin connection is based on 
`sample python scripts <https://github.com/MemDynLab/ZMQInterface/tree/master/python_clients>`_ created by Francesco Battaglia.

License
-------

GNU General Public License v3.0 or later.

See `LICENSE <https://github.com/hangyabalazs/opeth/blob/master/LICENSE>`_ for the full text.
