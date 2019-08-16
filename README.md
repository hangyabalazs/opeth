# OPETH
Online Peri-Event Time Histogram for [Open Ephys](http://www.open-ephys.org/gui).

Performs spike detection based on raw Open Ephys data exported via [ZeroMQ](https://zeromq.org). Requires triggers from Open Ephys for histogram display as spikes are detected around them.

## Usage

- Needs [ZMQInterface plugin](https://github.com/bandita137/ZMQInterface). For Windows a [precompiled dll](https://github.com/bandita137/ZMQInterface/releases/download/v0.2-pre/ZMQInterface.dll) is present. 
- Set up Open Ephys with ZMQInterface plugin. Plugin is recommended to be after bandpass filter and/or common average reference filter, but spike detector is not required.
- Start `opeth/gui.py`.