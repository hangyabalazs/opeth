'''Main class for setting up user interface and instantiate network connections.
'''

from __future__ import division
import sys
import traceback
import signal
import pyqtgraph as pg
from timeit import default_timer
import pickle # for storing parameters
from collections import defaultdict
from comm import CommProcess
from colldata import DataProc, EVENT_ROI, SAMPLES_PER_SEC, SPIKE_HOLDOFF
from pprint import pprint
import os.path
import re
import numpy as np
import math

# configparser: attempt for py3/py2.7 compatibility
try:
    import configparser
except ImportError:
    import ConfigParser as configparser

from pyqtgraph.Qt import QtGui, QtCore
from pyqtgraph.ptime import time as pgtime
from pyqtgraph.parametertree import Parameter, ParameterTree
import pyqtgraph as pg
from pyqtgraph.dockarea import DockArea, Dock

import logsetup
from spike_gui import SpikeEvalGui
import pgext

AUTOTRIGGER_CH = None       #: Set to None to disable, otherwise TTL pulses will be generated if given channel is over threshold
HISTOGRAM_BINSIZE = 0.001   #: Histogram bin size in seconds
CHANNELS_PER_HISTPLOT = 4   #: Channels per tetrode to be combined in histogram
PARAMFNAME = "lastini.conf" #: Last used ini file name stored in a file, will default to :data:`DEFAULT_INI` if missing
DEFAULT_INI = "default.ini" #: Config file name defaults
DEFAULT_SPIKE_THRESHOLD = 0.00003 #: Spike threshold set as default parameter if no ini file found.
TRIGGER_HOLDOFF = 0.001     #: Trigger holdoff in seconds
RERECORD = False            #: True if data is to be saved for debug purposes
SPIKEWIN = False            #: Set to True if one spike analysis window is to be opened at start.
HIDE_AUX_CHANNELS = True    #: Whether AUXiliary channels - in 35 channel case: last 3 channels, in 70 channel case last 6 - should be omitted.
CHANNELPLOTS_VERTICAL_OFFSET = 0.1  #: When histogram are presented with lines per channel, adjust the way they are plotted.
CHANNELPLOTS_ANTIALIASED = True #: More professional display for per channel plots, but less visible
NEGATIVE_THRESHOLD = True   #: Inverted signal - positive threshold value in params mean negative threshold with falling edge detection

DEBUG = False               #: Enable or disable debug mode
DEBUG_TIMING = False        #: Enable timing prints
DEBUG_FPS = False           #: Enable frame per sec debug prints
DEBUG_FPSREPORT_PERIOD = 5  #: FPS debug print update frequency

# CONSTANTS

# Column increment index:
# number of columns is 1 until more than 3 plots are to be displayed, 2 until more than 8 etc.
#  1:3 2:8  3:12  4:20-> 5 rows x 4 columns (plus one column for parameter setup)
#  .   ..   ...
#  .   ..   ...
#  .   ..   ...
#      ..   ...
# row x col: 3x1, 4x2, 4x3, 5x4, 5x5, 5x6, 6x7, 8x8, 10x9, 11x10...
COLUMN_INCREMENTS = [3, 8, 12, 20, 25, 30, 42, 64, 90, 110, 120, 130, 1000] #: A value in a given index means maximum number of plots displayed for the index number of columns

# Enumeration of the three different
PLOT_FLAT, PLOT_AGGREGATE, PLOT_CHANNELS = 'flat', 'aggregate', 'channels'
PLOT_TYPES = [PLOT_FLAT, PLOT_AGGREGATE, PLOT_CHANNELS]

VOLT_TO_UVOLT_MULTIPLIER = 1000000

# Histogram color assignments
BRUSHCOLORS = [(0,0,255,255), (0,220,220,255), (0,255,0,255), (0,180,0,255), # B,Cy,G,DarkG
               (220,0,220,255), (220,220,0,255), (140,140,140,255), (180,180,0,255)]
LINECOLORS = [(0,0,255,255), (255,0,0,255), (0,255,0,255), (255,255,0,255),
              (255,0,255,255),(0,255,255,255), (140,140,140,255), (0,180,0,255)]

class TimeMeasClass(object):
    '''Performance monitoring/profiling class. (Just for development.)
    
    Maintains a dictionary of elapsed times and number of calls with separate identifier strings
    to make it possible to measure multiple overlapping time segments.
    '''

    def __init__(self):
        self.timespent = defaultdict(int) #: Measurement array for elapsed time
        self.timestart = defaultdict(int) #: Last measurement's start time (initialized in :meth:`tic`)
        self.timecount = defaultdict(int) #: Number of measurements collected in :attr:`timespent` (for averaging)

    def tic(self, idstr):
        '''Start timer.
        
        Arguments:
            idstr (str): Starts timer for given string id. Will be terminated by :meth:`toc`.
        '''
        self.timestart[idstr] = default_timer()

    def toc(self, idstr):
        '''Stop timer, increment corresponding timer arrays.
        
        Arguments:
            idstr (str): Index string of :attr:`timespent` and :attr:`timecount`.
            
        Returns:
            elapsed time since last tic in seconds
        '''
        delta = default_timer() - self.timestart[idstr]
        self.timespent[idstr] += delta
        self.timecount[idstr] += 1
        return delta

    def dump(self):
        '''Display all timer results.'''
        for i in sorted(self.timestart.keys()):
            logger.debug("%15s: %f / %d" % (str(i), self.timespent[i], self.timecount[i]))

    def reset(self):
        '''Restart all timers.'''
        for i in sorted(self.timestart.keys()):
            self.timespent[i] = 0
            self.timecount[i] = 0


class GuiClass(object):
    '''Main GUI handling class.
    
    Creates windows:
    
    * Main histogram window with parameters.
    
    * Raw data window with real time plotted continuous scrolling waveform for overview.
    
    * Debug window if :data:`DEBUG` is True.
    
    * Spike analysis windows using :class:`spike_gui.SpikeEvalGui` when corresponding button is pressed.
    
    At startup as long as no data is present the histogram windows are not populated as the input data
    channel count is not known.
    
    The main loop performing the most important periodic operations is in :meth:`update`
    method, calling e.g. :meth:`comm.CommProcess.timer_callback` to collect data and based on that
    update plot data.
    '''

    MAX_PLOT_PER_SEC = 4    #: Perfomance limit through :attr:`earliest_hist_plot`

    def __init__(self):
        '''        
        Attributes:
            rawdata_curves (list):  Top part waveforms of raw analog window
            ttlraw_curves (list):   Bottom part waveforms of raw analog window
            cp (comm.CommProcess):  Interface and data collector to OE
            dataproc (colldata.DataProc):  Data processor instance working on :attr:`cp`'s :class:`colldata.Collector` data
            mainwin (QtGui.QMainWindow): Main window with histogram and parameter setup window
            rawdatawin (pyqtgraph.GraphicsWindow): Real time raw analog data display with a continuously scrolling part and a 
                TTL-aligned snapshot.
            debugwin (QtGui.QWidget): Opened only if :data:`DEBUG` is True, displays some internal variables for debugging
            spike_bin_ms (2D np.ndarray): Histogram bins, one row per channel, each row contains 
                :attr:`ttl_range_ms` + 1 number of bins for collecting spike offsets relative to event.
            ttl_range_ms (int):     TTL range specified by start and end value in :attr:`event_roi`
                (warning: if :data:`HISTOGRAM_BINSIZE` modified, it is not ms any more!)
            event_roi (list of two float elements): Region of interest around event ([start, end] values in second around
                TTL pulse for spike search region and plotting e.g. [-0.02, 0.05] for default 20 ms before, 50 ms after)
            configfname (str):       Name of config file for parameter setup storage. :data:`PARAMFNAME` points to the file
                from where its initial value is read during program startup.
            threshold_levels (np.ndarray of floats):  One row per tetrode, threshold level in uV. 
                Same sign both for negative and positive spikes as in GUI, will be adjusted afterwards for spike detection.
            histplots (list of lists of plots): Histogram plot collection for data updates - each element is a 
                collection of per-channel histograms for a given tetrode.
        '''
        self.rawdata_curves = []
        self.ttlraw_curves = []
        self.cp = CommProcess()
        self.dataproc = DataProc(self.cp.collector, HIDE_AUX_CHANNELS)
        self.initiated = False
        self.plotdistance = 0
        self.starttime = default_timer()

        # plotting stats
        self.framecnt = 0
        self.lastreport = default_timer()
        self.lastframecnt = 0
        self.elapsed = 0
        self.fpslist = []
        self.displayed_ttlcnt = 0
        self.earliest_rawttl_plot = 0   #: Next raw analog TTL-aligned display time - lower window update rate limit

        # spike positions
        self.raw_spikepos = []
        # todo: '_ms' depends on HISTOGRAM_BINSIZE, not necessarily ms!
        self.spike_bin_ms = None

        # parameters
        self.threshold_levels = None
        self.trigger_nearest_ts = 0.0
        self.channels_per_plot = CHANNELS_PER_HISTPLOT
        self.should_restore_params = True   #: Automatic parameter reload should happen only on startup.
        self.downsampling_rate = SAMPLES_PER_SEC // 1000 #: Downsampling rate is calculated from sampling rate, target is 1kHz for raw data window

        # true if system shutdown in progress
        self.closing = False

        self.earliest_hist_plot = default_timer()   #: Next histogram update time for performance cap

        self.timing_start = default_timer() #: Debug: internal elapsed time measurement scheduler
        self.timeas = TimeMeasClass()       #: Profiling class

        self.disabled_channels = []         #: A list of disabled channels starting with 0
        self.disabled_channel_update_at = None  # pyqtgraph parameters can't be updated from within the change handler?
        self.disabled_channel_update_to = ''    # doing that instead from the update routine

        self.event_roi = list(EVENT_ROI)

        self.configfname = "default.ini"
        self.force_update = False            #: Keep track of programmatic parameter changes to prevent infinite loops.

        if RERECORD:
            self.datafile = open('data.txt', 'wt')
            self.ttlfile = open('trigger.txt', 'wt')

        self.initgraph()
        self.mainwin.show()

    def initgraph(self):
        '''Called at startup to set up the main window with the parameter setup
        and the raw data window.

        Only a placeholder text is displayed instead of histogram plots until
        the first set of data arrived and channel count becomes known.
        '''
        assert(not self.initiated)

        self.init_rawwin()
        self.init_histwin()
        self.init_params(self.paramdock)

        if DEBUG:
            self.init_debugwin()
        if SPIKEWIN:
            self.init_spikewin()
        else:
            self.spikewins = []

    def update_channelcnt(self, nChannels):
        '''Called when number of channels becomes known or changes.

        Update the necessary display elements (number of histogram plots etc).

        Arguments:
            nChannels (int): number of input channels (as detected in first chunk of data received from OE)
        '''

        self.nPlotWindows =  int(math.ceil(nChannels / self.channels_per_plot)) #: Number of histogram plots, equals to ``self.nChannels/self.channels_per_plot``
        logger.info("Initializing for %d channel plots, %d histogram plots" % (nChannels, self.nPlotWindows))
        self.nChannels = nChannels

        if self.channels_per_plot == 2:
            self.plottitle = "Stereotrode"
        elif self.channels_per_plot == 4:
            self.plottitle = "Tetrode"
        elif self.channels_per_plot == 1:
            self.plottitle = "Channel"
        else:
            self.plottitle = "Plot"

        self.populate_rawwin()
        self.populate_histwin()
        self.populate_params()
        self.initiated = True

    def update_plotstyle(self):
        '''If the plot style changes from one of the histogram plots to channel plot
        or vica versa, the channel colors are to be updated.
        '''
        self.populate_params()

    def init_rawwin(self):
        '''Real time display of current waveform for visible feedback even when signal thresholds may be off.
        '''
        self.rawdatawin = pg.GraphicsWindow(title="Raw analog samples")

        self.rawplot = self.rawdatawin.addPlot(title="Analog samples")
        self.rawplot.setLabel('bottom', 'Index', units='Sample')

        #self.rawplot.setYRange(0, nPlots*6)
        #self.rawplot.setXRange(0, 30000)
        #self.rawplot.resize(600,900)

        self.rawdatawin.nextRow()
        self.ttlplot = self.rawdatawin.addPlot(title="Samples around event")


    def populate_rawwin(self):
        '''Create as many raw analog display curves as necessary based on :attr:`nChannels`
        '''

        self.rawplot.clear()
        self.ttlplot.clear()
        self.rawdata_curves = []
        self.ttlraw_curves = []

        # raw plots
        for i in range(self.nChannels):
            c = pg.PlotCurveItem(pen=(i, self.nChannels*1.3))
            self.rawplot.addItem(c)
            c.setPos(0, i*6)
            self.rawdata_curves.append(c)

        # TTL-aligned plots
        for i in range(self.nChannels):
            c = pg.PlotCurveItem(pen=(i, self.nChannels*1.3))
            self.ttlplot.addItem(c)
            c.setPos(0, -i*6)
            self.ttlraw_curves.append(c)
            self.ttlplot.setLabel('bottom', 'Spike time relative to event', units='ms')

    def init_histwin(self):
        '''Initialize main histogram window and parameters with defaults.

        Actual display will be updated in :meth:`populate_histwin` once number
        of channels/channels per tetrode is known.
        '''
        self.mainwin = QtGui.QMainWindow()
        self.mainwin.setWindowTitle('Online Peri-event Time Histogram')
        self.mainwin.resize(1200,800)
        # ugly shortcut to handle closing of the main window
        self.mainwin.closeEvtHnd = self.mainwin.closeEvent
        self.mainwin.closeEvent = self.onClose

        cw = QtGui.QWidget()
        self.mainwin.setCentralWidget(cw)
        l = QtGui.QHBoxLayout()
        self.hboxlayout = l
        cw.setLayout(l)

        self.histplotarea = DockArea()

        # display a placeholder window instead of histograms until data arrives
        waitDock = Dock("Awaiting data")
        msg = '<h2>Awaiting data... </h2><br/><h3>Please start Open Ephys!</h3><br/>'
        msg += '<table align="center">'
        msg += '<tr><th colspan=2 align="left" style="padding-left:1.5em">HARD-CODED DEFAULTS (see gui.py and colldata.py):</th></tr>'
        msg += '<tr><th align="left">Sampling rate (SAMPLES_PER_SEC):</th><td style="padding-left:1em">%d</td></tr>' % SAMPLES_PER_SEC
        msg += '<tr><th align="left">Spike censoring time (SPIKE_HOLDOFF):</th><td style="padding-left:1em">%.2f ms</td></tr>' % (SPIKE_HOLDOFF * 1000)
        msg += '<tr><th align="left">Histogram bin size (HISTOGRAM_BINSIZE):</th><td style="padding-left:1em">%.2f ms</td></tr>' % (HISTOGRAM_BINSIZE * 1000)        
        msg += '<tr><th align="left">Inverted spike detection (NEGATIVE_THRESHOLD):</th><td style="padding-left:1em">%s</td></tr>' % ('yes' if NEGATIVE_THRESHOLD else 'no')        
        msg += '</table>'
        label = QtGui.QLabel(msg)
        label.setAlignment(QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter)
        waitDock.addWidget(label)
        self.docks = [waitDock]

        self.histplotarea.addDock(waitDock, "left")

        params_area = DockArea()
        l.addWidget(self.histplotarea)
        l.addWidget(params_area)

        # last dock on the right side: parameters
        self.paramdock = Dock("Params")
        #self.docks.append(self.paramdock)
        params_area.addDock(self.paramdock, "left")

    def populate_histwin(self):
        '''Create an array of dockable/movable histograms.
        The layout is determined by the number of necessary plot windows and the
        :data:`COLUMN_INCREMENTS` variable.
        '''
        if hasattr(self, 'histwidgets'):
            for h in self.histwidgets:
                h.close()

        self.histplots = []
        self.histwidgets = []
        self.channelplots = []
        self.channel_line_pens = [] # pens collected for simple plot color adjustment

        # pyqtgraph behaves strangely when attempting to remove some
        # existing docks. Attempting to avoid popup windows for removed
        # docks...
        self.histplotarea.close()

        for d in self.docks:
            d.close()
            d.setParent(None)
            d.label.setParent(None)
        self.histplotarea.clear()

        self.hboxlayout.removeWidget(self.histplotarea)

        # Create a new histogram area - would be unnecessary under normal
        # circumstances; workaround for pyqtgraph

        self.histplotarea = DockArea()
        self.hboxlayout.insertWidget(0, self.histplotarea)

        # Rebuild layout with new plots
        self.docks = [Dock("%s %d" % (self.plottitle, idx + 1)) for idx in range(self.nPlotWindows)]

        # Determine layout of plots depending on self.nPlotWindows according to COLUMN_INCREMENTS list.
        # Number of columns is directly derived from COLUMN_INCREMENTS, based on that the number of
        # rows is also determined.
        # Actual layout will be filled from left to right, then top to bottom.

        cols = min(np.argwhere(np.array(COLUMN_INCREMENTS, dtype='int32') >= self.nPlotWindows))[0] + 1
        rows = int(math.ceil(self.nPlotWindows / cols))

        logger.info("Histogram plots: %d x %d grid" % (rows, cols))
        hasdocks = np.ones((rows, cols), dtype='int32')
        # last row may not be filled...
        empty = rows * cols - self.nPlotWindows
        self.docks += [Dock("") for idx in range(empty)]

        dockpos = np.argwhere(hasdocks)

        # fill in the dock order by placing elements one by one into the fitting default_layout
        dock_order = -np.ones((rows, cols), dtype="int32")

        for idx, d in enumerate(dockpos):
            dock_order[d[0], d[1]] = idx

        # now we know what goes where, fill the dock area
        validpos = np.argwhere(dock_order != -1)
        maxrow = max(validpos[:, 0])
        maxcol = max(validpos[:, 1])

        # first add top left plot
        self.histplotarea.addDock(self.docks[0], "left")

        # then add one plot at the start of each row
        for row in range(1, maxrow + 1):
            todock = dock_order[row, 0]
            docked_above = dock_order[row-1, 0]
            self.histplotarea.addDock(self.docks[todock], "bottom", self.docks[docked_above])

        # now add all the remaining plots in a given row
        for row in range(0, maxrow + 1):
            for col in range(1, maxcol + 1):
                if dock_order[row, col] == -1:
                    continue
                todock = dock_order[row, col]
                docked_to_left = dock_order[row, col-1]
                self.histplotarea.addDock(self.docks[todock], "right", self.docks[docked_to_left])

        self.histwidgets = [pg.PlotWidget(viewBox=pgext.DisabledMouseViewBox()) for i in range(self.nPlotWindows)]

        for idx, (d, w) in enumerate(zip(self.docks, self.histwidgets)):
            d.addWidget(w)
            w.setLabel('bottom', 'Spike time rel. to event', units='ms')
            # color order is reverse ch4[+3+2+1], ch3[+2+1], ch2[+1], ch1

            # For each display window there is a set of plots to be shown
            # Flat, aggregate view: histogram with bar graphs (stepMode: True)
            histplots = []
            for i in range(self.channels_per_plot):
                ch_id = idx * self.channels_per_plot + i
                color = BRUSHCOLORS[i] if ch_id not in self.disabled_channels else (255,255,255,0)
                hp = w.plot(np.arange(2), np.arange(1), stepMode=True, fillLevel=0, brush=color)
                # Make it sure that later channels of an aggregate plot are behind first channel
                # so first channel of a plot is at bottom of the stack.
                hp.setZValue(self.channels_per_plot - i)
                histplots.append(hp)

            # one last plot which is never disabled - for flat histograms
            histplots.append(w.plot(np.arange(2), np.arange(1), stepMode=True, fillLevel=0, brush=BRUSHCOLORS[0]))

            # All channels separately - would overlap so draw lines instead
            antialias = CHANNELPLOTS_ANTIALIASED

            channelplots = []
            for i in range(self.channels_per_plot):
                ch_id = idx * self.channels_per_plot + i
                color = LINECOLORS[i] if ch_id not in self.disabled_channels else (255,255,255,0)

                pen = pg.mkPen(color=color, width=1)
                self.channel_line_pens.append(pen)
                channelplots.append(w.plot(np.arange(1), np.arange(1), stepMode=False,
                            pen=pen, antialias=antialias))

            self.histplots.append(histplots)
            self.channelplots.append(channelplots)

        self.hist_x = np.linspace(self.event_roi[0], self.event_roi[1], int(round(
                (self.event_roi[1] - self.event_roi[0] + HISTOGRAM_BINSIZE) / HISTOGRAM_BINSIZE)))

    def update_plotcolors(self):
        '''Called when channels get disabled - no need to remove plots'''
        # channel colors update - piece of cake
        for ch_id in range(self.nChannels):
            color = LINECOLORS[ch_id % self.channels_per_plot] if ch_id not in self.disabled_channels else (255,255,255,0)
            self.channel_line_pens[ch_id].setColor(QtGui.QColor(*color))

        for plot_idx, histplot in enumerate(self.histplots):
            startid = plot_idx * self.channels_per_plot
            for i in range(self.channels_per_plot):
                ch_id = startid + i
                color = BRUSHCOLORS[i] if ch_id not in self.disabled_channels else (255,255,255,0)
                #histplot[i].setFillBrush(color) # this would not work - creates a QColor???
                # and causes a lot of exceptions
                histplot[i].opts['fillBrush'] = color

    def init_params(self, paramcontainer, reset=False, **kwargs):
        '''Prepare parameter setup part of main histogram window.'''

        # tetrode threshold parameters
        self.param = Parameter.create(name='params', type='group')
        self.par_ttl_src = Parameter.create(name='Event trigger channel', type='int', limits=(1,8))
        self.param.addChild(self.par_ttl_src)
        self.par_ch_per_plot = Parameter.create(name='Channels per plot', type='int',  limits=(1,8),
                                                value=CHANNELS_PER_HISTPLOT)
        self.param.addChild(self.par_ch_per_plot)

        self.par_disabled_ch = Parameter.create(name="Disabled channels", type='str', value="")
        self.param.addChild(self.par_disabled_ch)

        self.par_ttlroi_before = Parameter.create(name='ROI before event', type='float', value=self.event_roi[0], step=1e-3, siPrefix=True,
                                                  limits=(-500, 500), suffix='s')
        self.param.addChild(self.par_ttlroi_before)
        self.par_ttlroi_after = Parameter.create(name='ROI after event', type='float', value=self.event_roi[1], step=1e-3, siPrefix=True,
                                                 limits=(-500, 500), suffix='s')
        self.param.addChild(self.par_ttlroi_after)

        self.par_histcolor = Parameter.create(name='Histogram color', type='list', values=dict([(p, p) for p in PLOT_TYPES]))
        self.param.addChild(self.par_histcolor)

        self.par_common_thresh = Parameter.create(name='Spike threshold', type='float', value=DEFAULT_SPIKE_THRESHOLD, step=1e-3, siPrefix=True,
                                                  limits=(1e-6,5), suffix='V')
        self.param.addChild(self.par_common_thresh)

        # Per-tetrode threshold settings are empty at start
        self.par_tetrode_thresh = []
        self.param_custom_thresh = Parameter.create(name='Custom threshold levels', type='group', children=self.par_tetrode_thresh)
        self.param.addChild(self.param_custom_thresh)

        paramTree = ParameterTree()
        paramTree.setParameters(self.param, showTop=False)

        if reset:
            logger.info("Clearing up parameter layout")
            for i in reversed(range(paramcontainer.layout.count())):
                paramcontainer.layout.itemAt(i).widget().setParent(None)

        buttonsLayout = QtGui.QVBoxLayout()
        h1 = QtGui.QHBoxLayout()
        h2 = QtGui.QHBoxLayout()
        buttonsWidget = QtGui.QWidget()
        buttonsWidget.setLayout(buttonsLayout)
        row1 = QtGui.QWidget()
        row1.setLayout(h1)
        self.configbox = QtGui.QGroupBox("Config:")
        self.configbox.setLayout(h2)

        save_params_btn = QtGui.QPushButton('Save')
        save_params_btn.setMinimumWidth(5)
        save_as_params_btn = QtGui.QPushButton('Save as')
        save_as_params_btn.setMinimumWidth(5)
        load_params_btn = QtGui.QPushButton('Load')
        load_params_btn.setMinimumWidth(5)
        reset_params_btn = QtGui.QPushButton('Reset')
        reset_params_btn.setMinimumWidth(5)
        clear_btn = QtGui.QPushButton('Clear plot')
        open_spikes_btn = QtGui.QPushButton('Open new spike win')
        h1.addWidget(clear_btn)
        h1.addWidget(open_spikes_btn)
        h2.addWidget(save_params_btn)
        h2.addWidget(save_as_params_btn)
        h2.addWidget(load_params_btn)
        h2.addWidget(reset_params_btn)
        buttonsLayout.addWidget(row1)
        buttonsLayout.addWidget(self.configbox)

        paramcontainer.addWidget(buttonsWidget)
        paramcontainer.addWidget(paramTree)

        save_params_btn.clicked.connect(self.onSaveParams)
        save_as_params_btn.clicked.connect(self.onSaveAsParams)
        reset_params_btn.clicked.connect(self.onResetParams)
        load_params_btn.clicked.connect(self.onLoadParams)
        clear_btn.clicked.connect(self.onClearPlot)
        open_spikes_btn.clicked.connect(self.onOpenSpikeWin)

        self.param.sigTreeStateChanged.connect(self.onParamChange)

    def populate_params(self):
        '''Update parameter setup after channel count is known.'''

        self.param_custom_thresh.clearChildren()

        if self.threshold_levels is not None and len(self.threshold_levels) == self.nChannels:
            thresholds = list((self.threshold_levels / VOLT_TO_UVOLT_MULTIPLIER).ravel())
        else:
            thresholds = [self.par_common_thresh.value()] * self.nChannels

        # generate unique param names
        if self.channels_per_plot == 1:
            channel_names = ['Channel#%d:' % (ch + 1) for ch in range(self.nChannels)]
        else:
            channel_names = ['Ch#%d (%s#%d):' % (ch + 1, self.plottitle, ch//self.channels_per_plot + 1)
                             for ch in range(self.nChannels)]

        # fetch channel colors
        ch_colors = []
        if self.par_histcolor.value() == PLOT_CHANNELS:
            for ch in range(self.nChannels):
                channels = self.channelplots[ch // self.channels_per_plot]
                plot = channels[ch % self.channels_per_plot]

                ch_colors.append(plot.opts['pen'].brush().color().getRgb())
        elif self.par_histcolor.value() == PLOT_AGGREGATE:
            for ch in range(self.nChannels):
                hplots = self.histplots[ch // self.channels_per_plot]
                plot = hplots[ch % self.channels_per_plot]
                ch_colors.append(plot.opts['fillBrush'])
        else: # flat
            ch_colors = [BRUSHCOLORS[0]] * self.nChannels
            for ch in range(self.nChannels):
                if ch in self.disabled_channels:
                    ch_colors[ch] = (255, 255, 255, 0)

        # "channel" type parameter traslates to pgext.ChannelParameterItem
        self.par_tetrode_thresh = [Parameter.create(name=channel_names[i], type='channel',
                                   color=ch_colors[i], value=thresholds[i],
                                   step=1e-3, siPrefix=True, limits=(1e-6,5), suffix='V'
                                   ) for i in range(self.nChannels)]

        self.param_custom_thresh.addChildren(self.par_tetrode_thresh)

        if self.should_restore_params:
            self.restore_params()
            self.should_restore_params = False

        self.update_threshold_levels()

    def init_debugwin(self):
        '''Open a new debug window - called only if :data:`DEBUG` is enabled.'''
        self.debugwin = QtGui.QWidget()
        self.debugwin.setWindowTitle("OPSY/debug")
        l = QtGui.QVBoxLayout()
        self.debugwin.setLayout(l)

        self.debug_param = Parameter.create(name="debugparams", type="group")
        self.debug_ttlcnt = self.debug_param.addChild(Parameter.create(name="TTL count", type="int", value=0))
        self.debug_datamax = self.debug_param.addChild(Parameter.create(name="Data max", type="float", value=1e9))
        self.debug_datamin = self.debug_param.addChild(Parameter.create(name="Data min", type="float", value=-1e9))
        self.debug_trigdatamax = self.debug_param.addChild(Parameter.create(name="Trig. data max", type="float", value=1e9))
        self.debug_trigdatamin = self.debug_param.addChild(Parameter.create(name="Trig. data min", type="float", value=-1e9))
        self.debug_channelcnt = self.debug_param.addChild(Parameter.create(name="Channel cnt", type="int", value=self.nChannels))
        t = ParameterTree()
        t.setParameters(self.debug_param)
        l.addWidget(t)
        self.debugwin.show()

    def init_spikewin(self):
        ''' Single channel analysis window '''
        self.spikewins = [SpikeEvalGui(SAMPLES_PER_SEC)]

    def set_threshold_levels(self, value):
        '''Parameter setup: update all the tetrode threshold level values simultaneously.'''
        if hasattr(self, "par_tetrode_thresh"):
            for p in self.par_tetrode_thresh:
                p.setValue(value)
        else:
            logger.debug("tetrode_tresh: Noattr")

    def update_threshold_levels(self):
        '''Update the internal threshold levels based on the UI parameters.'''
        if hasattr(self, "par_tetrode_thresh") and hasattr(self, "nChannels"):
            vals = [p.value() for p in self.par_tetrode_thresh]
            levels = np.array(vals)
            self.threshold_levels = levels.reshape(self.nChannels, 1) * VOLT_TO_UVOLT_MULTIPLIER

    def more_than_two_continuous(self, intlist):
        '''In order to reduce a string of '1, 2, 3, 4' to '1-4' return the longest
        series of numbers incrementing by one at the beginning of an intlist.
        
        Helper function for :meth:`update_disabled_channels`, the opposite of
        :meth:`convert_strlist_to_ints` (partially).
        
        Parameters:
            intlist (list): a list of integers
            
        Returns:
            either the first element of `intlist` or a list of elements if 
            more than two consecutive numbers were incrementing by one. 
        '''
        if len(intlist) < 3:
            return [intlist[0]]
        else:
            res = [intlist[0]]
            for i in intlist[1:]:
                if res[-1] + 1 == i:
                    res.append(i)
                else:
                    break
            if len(res) >= 3:
                return res
            else:
                return [intlist[0]]

    def convert_strlist_to_ints(self, str_in):
        '''Convert a text entry of disabled channels to an integer list.
        
        Parameters: 
            str_in (str): input string in the format ``1-4, 17, 30-33``.
        
        Returns:
            a list of integers like ``[1,2,3,4,17,30,31,32,33]``.
        '''
        drep = str_in.replace(',', ' ')
        drep = re.sub(' +', ' ', drep)
        dsplit = drep.split('-')
        dlist = []
        last_end = None
        for s in dsplit:
            try:
                vals = [int(v) for v in s.split(' ')]
            except ValueError as e:
                vals = []
            if vals:
                if last_end is not None:
                    dlist.extend(range(last_end, vals[0]+1))
                    dlist.extend(vals[1:-1])
                else:
                    dlist.extend(vals[:-1])
                last_end = vals[-1]
        if last_end is not None and last_end not in dlist:
            dlist.append(last_end)
        return dlist

        remainder = sorted(dlist)
        results = []
        while remainder:
            res = self.more_than_two_continuous(remainder)
            if len(res) > 1:
                results.append(str(res[0]) + "-" + str(res[-1]))
            else:
                results.append(str(res[0]))
            remainder = remainder[len(res):]

    def update_disabled_channels(self):
        '''Called when list of disabled channels is entered; it parses 
        the input string to understand and abbreviate series of numbers.
        
        Uses :meth:`convert_strlist_to_ints` and reproduces the string 
        with :meth:`more_than_two_continuous` in order to verify syntax
        and to combine input like ``1, 2, 3`` to ``1-3``.
        '''

        self.disabled_channels = []
        distr = self.par_disabled_ch.value()
        dis_list = self.convert_strlist_to_ints(distr)
        self.disabled_channels = sorted([d-1 for d in dis_list])

        remainder = sorted(dis_list)
        results = []
        while remainder:
            res = self.more_than_two_continuous(remainder)
            if len(res) > 1:
                results.append(str(res[0]) + "-" + str(res[-1]))
            else:
                results.append(str(res[0]))
            remainder = remainder[len(res):]
        distr2 = ", ".join(results)

        self.update_plotcolors()
        self.populate_params()

        if self.par_disabled_ch.value() != distr2:
            self.disabled_channel_update_at = default_timer()+.1
            self.disabled_channel_update_to = distr2

    def change_event_roi(self, new_roi, clear_plot=True, **kwargs):
        '''Change region of interest around event (spike search range) and
        update plots.
        '''

        self.event_roi[0] = new_roi[0]
        self.event_roi[1] = new_roi[1]
        if new_roi[1]-new_roi[0] < 0.02:
            self.event_roi[1] = new_roi[0] + 0.02

        self.ttl_range_ms = int(round( (self.event_roi[1] - self.event_roi[0]) / HISTOGRAM_BINSIZE))

        self.hist_x = np.linspace(self.event_roi[0], self.event_roi[1], int(round(
                                  (self.event_roi[1] - self.event_roi[0] + HISTOGRAM_BINSIZE) / HISTOGRAM_BINSIZE)))

        if clear_plot:
            self.onClearPlot()
        logger.info("Stimulus roi updated:" + str(self.event_roi))


    def onParamChange(self, param, changes):
        '''Called on any parameter change.'''
        need_threshupdate = False

        for param, change, data in changes:
            if param == self.par_common_thresh and change == 'value':
                self.set_threshold_levels(data)
                need_threshupdate = True
            elif param == self.par_ttlroi_before and change == 'value':
                self.change_event_roi((data, self.event_roi[1]))
            elif param == self.par_ttlroi_after and change == 'value':
                self.change_event_roi((self.event_roi[0], data))
            elif param == self.par_disabled_ch and change == 'value':
                self.update_disabled_channels()
            elif param in self.par_tetrode_thresh and change == 'value':
                need_threshupdate = True
            elif param == self.par_ch_per_plot and change == 'value':
                self.channels_per_plot = int(self.par_ch_per_plot.value())
                self.update_channelcnt(self.cp.collector.channel_cnt())
            elif param == self.par_histcolor and change == 'value':
                self.update_plotstyle()

        if need_threshupdate:
            self.update_threshold_levels()

    def restore_params(self):
        '''Startup code performing parameter restoration.'''

        # read the most recently used parameter setup file
        if os.path.isfile(PARAMFNAME):
            self.configfname = open(PARAMFNAME).read().strip()
            self.update_cfgboxtitle()
        else:
            self.configfname = DEFAULT_INI

        self.load_params()

    def onSaveParams(self):
        self.store_lastconfname(self.configfname)
        self.save_params()

    def onSaveAsParams(self):
        '''Store parameter setup in file. Called when corresponding button pressed.'''
        fname = QtGui.QFileDialog.getSaveFileName(None, 'Save setup', '.', '*.ini')[0]
        if fname:
            self.store_lastconfname(fname)
            self.save_params()

    def onLoadParams(self):
        fname = QtGui.QFileDialog.getOpenFileName(None, 'Open setup', '.', '*.ini')[0]
        if fname:
            self.store_lastconfname(fname)
            self.load_params()

    def update_cfgboxtitle(self):
        '''Update config box title to show the current config file, reduce length if necessary.
        '''
        title = "Config: " + self.configfname
        if len(title) > 50:
            title = title[:22] + "..." + title[-25:]
        self.configbox.setTitle(title)

    def store_lastconfname(self, fname):
        '''Store :attr:`configfname` in file :data:`PARAMFNAME` and update config box display to
        show new file name.

        Attributes:
            fname (str): Path to new file - if left empty then will default to :data:`DEFAULT_INI`.
        '''
        if fname == '':
            self.configfname = DEFAULT_INI
        else:
            self.configfname = fname
        self.update_cfgboxtitle()
        try:
            with open(PARAMFNAME, 'wt') as f:
                f.write(self.configfname)
        except Exception as e:
            logger.error("Unable update last used config file")
            logger.error(str(e))

    def save_params(self):
        '''Save parameters to :attr:`configfname`

        Called when Save or Save as buttons pressed.
        '''
        logger.info("Storing current parameters to: %s" % self.configfname)
        cfg = configparser.ConfigParser()

        # update parameters
        cfg.add_section("plot")
        cfg.set("plot", "histogram_type", self.par_histcolor.value())
        ch_per_plot = int(self.par_ch_per_plot.value())
        cfg.set("plot", "channels_per_plot", self.par_ch_per_plot.value())

        cfg.add_section("processing")
        cfg.set("processing", "ttl_trigger_channel", self.par_ttl_src.value())
        cfg.set("processing", "roi_before", self.par_ttlroi_before.value())
        cfg.set("processing", "roi_after", self.par_ttlroi_after.value())
        cfg.set("processing", "spike_nthreshold", self.par_common_thresh.value())
        thresholds = [str(p.value()) for p in self.par_tetrode_thresh]
        cfg.set("processing", "spike_nthreshold_channels", ",".join(thresholds))
        cfg.set("processing", "disabled_channels", self.par_disabled_ch.value())

        # store config options
        with open(self.configfname, 'wb') as configfile:
            cfg.write(configfile)

    def load_params(self):
        '''Load parameters from config file :attr:`configfname`

        Called after file selection dialog when Load button pressed, and also
        when program is first loaded.
        '''
        logger.info("Loading parameters from: %s" % self.configfname)

        cfg = configparser.ConfigParser()
        cfg.read(self.configfname)

        # restore parameters one by one
        if cfg.has_option("plot", "histogram_type"):
            histcolor = cfg.get("plot", "histogram_type")
            if histcolor in PLOT_TYPES:
                self.par_histcolor.setValue(histcolor)
            else:   # default if unknown type encountered
                self.par_histcolor.setValue(PLOT_FLAT)

        if cfg.has_option("processing", "roi_before"):
            before = cfg.getfloat("processing", "roi_before")
            self.par_ttlroi_before.setValue(before)
        else:
            before = self.par_ttlroi_before.value()

        if cfg.has_option("processing", "roi_after"):
            after = cfg.getfloat("processing", "roi_after")
            self.par_ttlroi_after.setValue(after)
        else:
            after = self.par_ttlroi_after.value()
        self.change_event_roi((before, after), clear_plot=False)

        # Update system level threshold...
        if cfg.has_option("processing", "spike_nthreshold"):
            threshold = cfg.getfloat("processing", "spike_nthreshold")
            self.par_common_thresh.setValue(threshold)
            self.set_threshold_levels(threshold)

        # ...and channel specific threshold levels
        if cfg.has_option("processing", "spike_nthreshold_channels"):
            ch_threshold = cfg.get("processing", "spike_nthreshold_channels")
            thr = ch_threshold.split(",")
            common_size = min(len(self.par_tetrode_thresh), len(thr))

            for par, thr in zip(self.par_tetrode_thresh[:common_size], thr[:common_size]):
                par.setValue(float(thr))

        if cfg.has_option("processing", "ttl_trigger_channel"):
            triggerch = cfg.getint("processing", "ttl_trigger_channel")
            self.par_ttl_src.setValue(triggerch)

        if cfg.has_option("processing", "disabled_channels"):
            disabled = cfg.get("processing", "disabled_channels")
            self.par_disabled_ch.setValue(disabled)

        self.force_update = True

    def onResetParams(self):
        '''Remove saved parameters and reinit parameter setup. Called when
        corresponding button was pressed.'''

        if os.path.isfile(PARAMFNAME):
            os.remove(PARAMFNAME)
        self.init_params(self.paramdock, self.nChannels, reset=True)

        # todo: self.paramchange should be called but that requires some extra arguments...
        self.update_threshold_levels()
        self.update_disabled_channels()

    def onOpenSpikeWin(self):
        '''Open new spike analysis window on button press.'''
        self.spikewins.append(SpikeEvalGui(SAMPLES_PER_SEC))

    def onClearPlot(self):
        '''Manually clear plots on button press.'''
        self.spike_bin_ms = np.zeros((self.cp.collector.channel_cnt(), self.ttl_range_ms + 1))
        self.force_update = True

    def update_histograms(self):
        '''Update displayed histogram plots.
        
        Types of histogram plots available:
        
        * the normal histogram with e.g. 4 channels per tetrode combined
            into a single histogram, channels indistinguishable
        
        * same histogram but each channel with its own colour, a histogram
            bar consisting of Ch1+Ch2+Ch3+Ch4 separated by colour 
            (same outline as in previous case just 4 colours instead of 1)

            Trick for display: 4 plots displayed,
            ch1 in front, ch1+ch2 aggregated behind etc.

        * per channel: lines instead of bar graphs to make it possible to
            distinguish between overlapping elements
        '''

        spike_bin_ms_disabled = self.spike_bin_ms.copy()
        spike_bin_ms_disabled[self.disabled_channels] = np.zeros((len(self.disabled_channels), spike_bin_ms_disabled.shape[1]))

        for plot_idx, histplot in enumerate(self.histplots):
            if self.par_histcolor.value() == PLOT_AGGREGATE:
                # In 4 channel case 4 histograms displayed per tetrode:
                # One summing all 4 channels, one summing only first 3, first 2 and last one containing only ch#1
                # This way a 4-colour histogram will "add up" a composite histogram and per-channel events are distingushable
                startid = plot_idx * self.channels_per_plot
                for i in range(self.channels_per_plot):
                    sum_spikes = np.sum(spike_bin_ms_disabled[ startid : startid + i + 1], axis=0)
                    idx = i #self.channels_per_plot - 1 - i
                    histplot[idx].setData(self.hist_x * 1000, sum_spikes[:-1])
                histplot[-1].setData([0,0], [0])
            elif self.par_histcolor.value() == PLOT_FLAT:
                # normal single-coloured histogram merging 4 channels into one plot
                sum_spikes = np.sum(spike_bin_ms_disabled[plot_idx*self.channels_per_plot:(plot_idx+1)*self.channels_per_plot], axis=0)

                for i in range(self.channels_per_plot)[::-1]:
                    # make it sure the other colors of per-channel accumulated histogram do not interfere
                    histplot[self.channels_per_plot-1-i].setData(self.hist_x * 1000, [0] * (len(self.hist_x) - 1) )

                histplot[-1].setData(self.hist_x * 1000, sum_spikes[:-1])
            else: # PLOT_CHANNELS
                # clean up the other display format
                for p in histplot:
                    # clear plot
                    p.setData([0,0], [0])

        for plot_idx, channelplot in enumerate(self.channelplots):
            # Per channel histograms (overlapping -> using lines instead of bars)
            if self.par_histcolor.value() == PLOT_CHANNELS:
                startid = plot_idx * self.channels_per_plot
                for i in range(self.channels_per_plot-1,-1,-1):
                    channelplot[i].setData(self.hist_x, spike_bin_ms_disabled[startid + i]
                                           + (self.channels_per_plot-i-1) * CHANNELPLOTS_VERTICAL_OFFSET)
            else:
                # clean up in case of other display formats
                for p in channelplot:
                    # clear plot
                    p.setData([0], [0])

    def update_spikewins(self, data_ts, data, spike_ts, spike_pos):
        '''Perform an update on spike windows.'''
        for spikewin in self.spikewins:
            if NEGATIVE_THRESHOLD:
                spikewin.plot(data_ts, data, spike_ts, spike_pos, -self.threshold_levels)
            else:
                spikewin.plot(data_ts, data, spike_ts, spike_pos, self.threshold_levels)

    def update(self, **kwargs):
        ''' 
        The main loop, processes input data and updates plots. Called periodically from a Qt timer.

        On very first round with actual data present it calls :meth:`update_channelcnt` to
        create the necessary amount of histogram plots.
        
        Periodically calls 
        
        * :meth:`comm.CommProcess.timer_callback` to fetch new data
        
        * :meth:`colldata.Collector.keep_last` to drop old data
        
        * :meth:`colldata.Collector.process_ttl` to fetch region of interest around TTL
        
        * :meth:`colldata.DataProc.compress` to reduce complexity of the real time plot
        
        * :meth:`colldata.DataProc.spikedetect` to find spikes
        
        * update spike analysis windows :meth:`update_spikewins`
        
        and updates real time plot data via :attr:`rawdata_curves` and :attr:`ttlraw_curves`
        
        Attributes:
            spike_bin_ms (2D numpy array): Histogram bins containing one row per channel of spike event 
                counter bins (accumulating);
                first item per row contains the bin corresponding to start of trigger area ( :attr:`event_roi` [0] )
                and last one to the end ( :attr:`event_roi` [1] )
            data_at_ttl (2D numpy array): Each row contains the same number of samples from different channels
            data_ts (1D numpy array): Timestamps of :attr:`data_at_ttl` samples around TTL
                (in seconds, used for binning)
            data_ts_0 (1D numpy array): Same array as data_ts, start offset removed (timestamp of first sample is 0), 
                used for histogram generation (binning)
            data_ts_roi (1D numpy array): TTL timestamps with actual TTL event aligned to 0 (one ts for each 
                sample - samples start earlier than TTL), used for plotting the time scale
            spike_pos (list of lists): each internal list contains sample index of spike events for a given channel 
                (events over threshold, disabled channels not included)
            spike_ts (list of lists): Same layout as :attr:`spike_pos`, contains the actual timestamps
                of spikes for plotting x axis
        '''

        # don't try to update when windows are being closed - would throw errors
        if self.closing:
            return

        # workaround for pyqtgraph parameter update trouble:
        #  objective is to correct disabled channel entry but can't do that immediately, should be done delayed
        #  to avoid infinite loop
        if  self.disabled_channel_update_at is not None and self.disabled_channel_update_at < default_timer():
            self.disabled_channel_update_at = None
            self.par_disabled_ch.setValue(self.disabled_channel_update_to)

        # statistics
        self.framecnt += 1

        # diagram update frequency statistics
        if default_timer() - self.lastreport > DEBUG_FPSREPORT_PERIOD:
            fps = (self.framecnt - self.lastframecnt) / (default_timer() - self.lastreport)
            self.fpslist.append(fps)
            if DEBUG_FPS:
                logger.info("\r%.1f updates / sec [%.1f - %.1f], compr: %.3f @ %.1f" % (
                               fps, min(self.fpslist), max(self.fpslist),
                               self.elapsed, default_timer() - self.starttime))

            if len(self.fpslist) > 50:
                self.fpslist = self.fpslist[-50:]
            self.lastreport = default_timer()
            self.lastframecnt = self.framecnt
            self.elapsed = 0

        ############################
        # actual ZMQ data processing 
        self.timeas.tic("full")
        self.timeas.tic("01 timer_cb")
        self.cp.timer_callback()
        self.timeas.toc("01 timer_cb")

        if not self.initiated and self.cp.collector.has_data():
            try:
                self.update_channelcnt(self.cp.collector.channel_cnt())
            except Exception as e:
                logger.error("Error in initgraph:" + str(e))
                traceback.print_exc()
                exit()
            self.ttl_range_ms = int(round( (self.event_roi[1] - self.event_roi[0]) / HISTOGRAM_BINSIZE))
            self.spike_bin_ms = np.zeros((self.cp.collector.channel_cnt(), self.ttl_range_ms + 1))

        # wait until threshold params set up...
        if self.threshold_levels is None:
            return

        self.timeas.tic("02-keeplast")
        # periodic data display
        self.cp.collector.keep_last(seconds=1)
        self.timeas.toc("02-keeplast")

        self.timeas.tic("03-data")
        data = self.cp.collector.get_data()
        ts = self.cp.collector.get_ts()
        if data is None:
            return

        dmin, dmax = data.min(), data.max()
        self.plotdistance = max(self.plotdistance, dmax - dmin)

        start = default_timer()

        # realtime display of 1 sec long signals - reducing plot complexity
        datacomp, tscomp = self.dataproc.compress(data, self.downsampling_rate, ts)
        tscomp = tscomp - tscomp[0] # start time from 0
        self.elapsed += default_timer() - start
        self.timeas.toc("03-data")

        if RERECORD:
            self.datafile.write('----- %d\n' % self.framecnt)
            for timestamp, datapoint in zip(ts, data[0]):
                self.datafile.write('%d, %.1f\n' % (timestamp, datapoint))

        self.timeas.tic("04-curves")
        for i in range(len(self.rawdata_curves)):
            self.rawdata_curves[i].setData(tscomp, datacomp[i] - 1.5 * i * self.plotdistance)
        self.timeas.toc("04-curves")

        # In case there's no trigger from open ephys we can simulate it
        thresh_levels = -self.threshold_levels if NEGATIVE_THRESHOLD else self.threshold_levels
        if AUTOTRIGGER_CH is not None:
            # hack: inject TTL events (no actual HW to generate TTL, can't make OE properly play back TTLs)
            ttl = self.dataproc.autottl(data, ts, self.cp.collector.timestamp,
                                        ch=AUTOTRIGGER_CH, threshold=thresh_levels[0])

            if ttl is not None:
                self.cp.add_event(ttl)

        if DEBUG:
            self.debug_datamin.setValue(data.min())
            self.debug_datamax.setValue(data.max())

        #### TTL processing
        was_new_data = False
        data_ts_roi = None

        while 1:
            # TTL processing loop: process as many TTLs as present then break.

            self.timeas.tic("05-process_ttl")
            data_at_ttl, data_ts = self.cp.collector.process_ttl(ttl_ch=self.par_ttl_src.value() - 1,
                                                                 start_offset=self.event_roi[0],
                                                                 end_offset=self.event_roi[1],
                                                                 trigger_holdoff=TRIGGER_HOLDOFF)
            self.timeas.toc("05-process_ttl")

            #print "TTL SRC:", self.par_ttl_src.value()
            #print "DATA_at_ttl:", data_at_ttl
            #if data_at_ttl is not None:
            #    print "DATA_at_ttl len:", len(data_at_ttl[0])
            #    print "Data ts: ", data_ts[:2], "...", data_ts[-1]
            #else:
            #    print "No DATA"
            #print "TTL ts", data_ts

            if data_at_ttl is None:
                break

            last_data_at_ttl = data_at_ttl
            last_data_ts = data_ts

            if RERECORD:
                self.ttlfile.write('----- %d\n' % self.framecnt)
                for ttlstamp, ttldatapoint in zip(data_ts, data_at_ttl[0]):
                    self.ttlfile.write('%d, %.1f\n' % (ttlstamp, ttldatapoint))

            self.displayed_ttlcnt += 1

            if DEBUG:
                self.debug_ttlcnt.setValue(self.displayed_ttlcnt)

            if len(data_ts) == 0:
                return
            data_ts = data_ts / float(SAMPLES_PER_SEC) # adjusted to seconds (instead of sample index)

            data_ts_0 = data_ts - data_ts[0]    # timestamps starting at 0 for first sample
            data_ts_roi = data_ts_0 + self.event_roi[0]           # and to the TTL window (-20ms..+50ms)

            self.timeas.tic("06-spikedetect")
            # todo: check whether spike_ts can be used instead of data_ts[spike_pos[ch]]

            spike_pos, spike_ts = self.dataproc.spikedetect(data_at_ttl, data_ts_roi,
                                                            threshold=thresh_levels,
                                                            rising_edge=not NEGATIVE_THRESHOLD,
                                                            disabled = self.disabled_channels)

            # Calculate spike times in millisec from sample positions
            # and increment the proper histogram bins based on that value.
            # todo: use vector operations instead of loop? - not a performance bottleneck right now

            self.timeas.toc("06-spikedetect")
            self.timeas.tic("06-spikehist")
            all_spike_cnt = 0
            for chnum, poslist in enumerate(spike_pos):
                for pos in poslist:
                    ts_binpos = round(data_ts_0[pos] / HISTOGRAM_BINSIZE)
                    ti_binpos = int(ts_binpos)
                    self.spike_bin_ms[chnum, ti_binpos] += 1
                    all_spike_cnt += 1

            self.timeas.toc("06-spikehist")

            #if all_spike_cnt == 0:
            if DEBUG:
                self.debug_trigdatamax.setValue(data_at_ttl.max())
                self.debug_trigdatamin.setValue(data_at_ttl.min())

            was_new_data = True

        self.timeas.tic("07-plot")

        # If no new data was present then there is no need to update 
        if was_new_data or self.force_update:
            self.force_update = False
            if self.earliest_rawttl_plot < default_timer():
                # display updates
                self.ttlplot.setTitle("Samples around event #%d (@%.3f)" % (self.displayed_ttlcnt, default_timer()-self.starttime))

                self.earliest_rawttl_plot = default_timer() + 0.5 # update twice per sec
                #datacomp, tscomp = self.dataproc.compress(last_data_at_ttl, 30, data_ts_roi)

                for i in range(len(self.ttlraw_curves)):
                    if data_ts_roi is not None:
                        self.ttlraw_curves[i].setData(data_ts_roi * 1000, last_data_at_ttl[i] - 1.5*i*self.plotdistance)

            if self.spikewins:
                if data_ts_roi is not None:
                    self.update_spikewins(data_ts_roi, last_data_at_ttl, spike_ts, spike_pos)

            if default_timer() > self.earliest_hist_plot:
                self.update_histograms()
                self.earliest_hist_plot = default_timer() + 1.0 / self.MAX_PLOT_PER_SEC
            #else:
            #    print "Histogram update skipped - too frequent"
        self.timeas.toc("07-plot")
        self.timeas.toc("full")

        if DEBUG_TIMING:
            if self.timing_start + 1 < default_timer():
                logger.debug("Timing")
                self.timeas.dump()
                self.timeas.reset()
                self.timing_start = default_timer()

    def onClose(self, event):
        '''Handler for closeEvent of main window (histogram window), should close all other windows 
        before closing the main window.'''

        self.closing = True

        self.rawdatawin.close()

        if DEBUG:
            self.debugwin.close()

        if self.spikewins:
            for win in self.spikewins:
                win.close()

        self.mainwin.closeEvtHnd(event)

# exit on CTRL+C: https://stackoverflow.com/questions/4938723/what-is-the-correct-way-to-make-my-pyqt-application-quit-when-killed-from-the-co
def sigint_handler(*args):
    '''Handler for the SIGINT signal in order to be able to quit pressing CTRL+C in console.'''
    QtGui.QApplication.quit()

logger = logsetup.init_logs("logs.txt")

if __name__ == '__main__':
    
    app = QtGui.QApplication([])
    ui = GuiClass()

    # CTRL+C quits Qt app
    signal.signal(signal.SIGINT, sigint_handler) 

    timer = QtCore.QTimer()
    timer.timeout.connect(ui.update)
    timer.start(20)

    if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
        QtGui.QApplication.instance().exec_()
